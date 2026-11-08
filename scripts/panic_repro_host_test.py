#!/usr/bin/env python3
"""Host-only #149 checks: command isolation, failed trials, and injected GRO corruption.

No hardware imports or access. The C fixture compiles the bucket walker extracted
verbatim from 300-45; it does not replace a target kernel build or board test.
"""
import argparse
import contextlib
import io
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

import panic_repro_trial as pr
import stack_normalize as sn

ROOT = Path(__file__).resolve().parent.parent


class ReproTests(unittest.TestCase):
    def test_clock_recipe_and_one_variable_arms(self):
        args = ['owrt', '--clock-set', 'common', '--image', 'openwrt-ours-clean',
                '--normalize', '--no-perf', '--tcp']
        base = dict(pr.command_plan(pr.parse_args(args), 'test'))
        self.assertEqual(base['ramload'].count('--pre'), 2)
        self.assertIn('--stock-clocks', base['ramload'])
        self.assertNotIn('perf', base)
        self.assertNotIn('zc-perf', base)
        for opt, value in [('--rps-mask', '1'), ('--qdisc', 'fq_codel'),
                           ('--gro-mode', 'list-off'), ('--napi', 'irq0')]:
            arm = dict(pr.command_plan(pr.parse_args(args + [opt, value]), 'test'))
            self.assertEqual(arm['ramload'], base['ramload'])
            self.assertIn(value, arm['normalise'])
            self.assertEqual(arm['zc-noperf'] == base['zc-noperf'], opt != '--napi')
        self.assertLess(list(base).index('normalise'), list(base).index('mode'))
        self.assertLess(list(base).index('status'), list(base).index('zc-noperf'))

    def test_invalid_argument_combinations(self):
        for args in [['owrt'], ['owrt', 'turbo', '--clock-set', 'common'],
                     ['owrt', 'turbo', '--kernel', 'plain.bin'],
                     ['owrt', 'turbo', '--gro-mode', 'off'],
                     ['owrt', 'turbo', '--tcp']]:
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                pr.parse_args(args)

    def test_dry_run_has_no_board_or_file_access(self):
        with patch.object(pr, 'run', side_effect=AssertionError), patch.object(pr, 'ssh', side_effect=AssertionError), \
                contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(pr.main(['plain', '--clock-set', 'common', '--kernel', 'mainline-7.4-rc1-clean3.bin',
                                      '--normalize', '--no-perf', '--dry-run']), 0)
        self.assertIn('clean3.bin', out.getvalue())

    def trial(self, failure=None, panic=False, alive=True, reboot=False):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / 'tmp/logs').mkdir(parents=True)
            console = root / 'console.log'
            console.write_text('')
            calls, messages, ids = [], [], iter(["before", "after" if reboot else "before"])

            def run(name, cmd, out):
                calls.append(cmd)
                out.write_text('test traffic output')
                if name == 'zc' and panic:
                    console.write_text('rteth-gro-diag: overlapping-rx\n')
                return 124 if name == failure else 0

            def ssh(cmd, t=8):
                if cmd == 'cat /proc/sys/kernel/random/boot_id':
                    return next(ids)
                if cmd == 'cat /proc/uptime':
                    return '91.0 0.0'
                return '91.0' if alive or 'devmem' in cmd or 'dmesg' in cmd else None

            with patch.multiple(pr, ROOT=root, LOG=root / 'test.log', CON=console), \
                    patch.object(pr, 'run', side_effect=run), patch.object(pr, 'ssh', side_effect=ssh), \
                    patch.object(pr, 'log', side_effect=messages.append):
                rc = pr.main(['plain', '--clock-set', 'common', '--normalize', '--no-perf'])
            return rc, calls, messages

    def test_failed_setup_does_not_run_traffic(self):
        rc, calls, messages = self.trial(failure='nat')
        self.assertEqual(rc, 2)
        self.assertFalse(any('scripts/zc_bench.py' in c for c in calls))
        self.assertIn('INVALID', messages[-1])

    def test_failed_traffic_or_snapshot_is_invalid(self):
        for phase in ['zc', 'normalise']:
            rc, _, messages = self.trial(failure=phase)
            self.assertEqual(rc, 2)
            self.assertIn('INVALID', messages[-1])

    def test_silent_reboot_is_not_a_clean_trial(self):
        self.assertEqual(self.trial(reboot=True)[0], 2)

    def test_panic_and_health_are_separate(self):
        self.assertEqual(self.trial(panic=True)[0], 1)
        self.assertEqual(self.trial(alive=False)[0], 2)
        self.assertEqual(self.trial()[0], 0)

    def test_normalizer_shell_and_independent_offloads(self):
        for napi in ['irq0', 'irq1', 'default']:
            for mode in ['on', 'list-off', 'off']:
                a = argparse.Namespace(stack='B', ip='192.168.25.56', napi=napi, qdisc='noqueue', gro_mode=mode, rps_mask='1')
                script = sn.normalize_script(a)
                subprocess.run(['sh', '-n'], input=script, text=True, check=True)
                self.assertIn('echo 1 > $q', script)
                line = next(x for x in script.splitlines() if 'ethtool -K' in x)
                self.assertIn('gro ' + ('off' if mode == 'off' else 'on'), line)
                self.assertIn('rx-gro-list ' + ('on' if mode == 'on' else 'off'), line)
        self.assertEqual(sn.OFFLOADS['gro'], 'on')
        self.assertEqual(sn.OFFLOADS['rx-gro-list'], 'on')

    def test_tcp_trigger_refuses_missing_or_failed_measurements(self):
        # nat_bench discovers a physical host NIC at import; replace only that
        # dependency so this remains a genuinely host-only check.
        spec = importlib.util.spec_from_file_location('zc_test', ROOT / 'scripts/zc_bench.py')
        zc = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {'nat_bench': types.ModuleType('nat_bench')}):
            spec.loader.exec_module(zc)
        good = "RESULT stack: 100.0 Mbit/s {} | eth0 rx 110.0 Mbit/s 1000 pps"
        for rc, text in [(1, good), (0, ''), (0, good.replace('100.0', '0.0'))]:
            result = subprocess.CompletedProcess([], rc, text, '')
            with patch.object(zc, 'zc', return_value={}), patch.object(zc.subprocess, 'run', return_value=result), \
                    self.assertRaises(RuntimeError):
                zc.run_tcp('stack', 12, False)

    def test_rx_owner_guard_allows_migration_only_after_release(self):
        text = (ROOT / 'openwrt/patches/300-45-net-rteth-gro-diagnostics.patch').read_text()
        added = '\n'.join(x[1:] for x in text.splitlines() if x.startswith('+') and not x.startswith('+++'))
        helpers = added[added.index('static bool gro_diag;'):added.index('#else')]
        c = r"""
#include <stdbool.h>
#include <stdint.h>
#include <stdlib.h>
#include <stdatomic.h>
#include <setjmp.h>
#include <assert.h>
#define MODULE_PARM_DESC(...)
#define module_param(...)
#define PAGE_SIZE 4096
#define IS_ALIGNED(p,a) (!((p)&((a)-1)))
#define READ_ONCE(x) (x)
#define BIT(b) (1UL << (b))
#define GRO_HASH_BUCKETS 8
static int cpu;
static jmp_buf escape;
static int raw_smp_processor_id(void) { return cpu; }
typedef _Atomic int atomic_t;
static int atomic_read(atomic_t *p) { return atomic_load(p); }
static int atomic_cmpxchg(atomic_t *p,int old,int next) { atomic_compare_exchange_strong(p,&old,next); return old; }
static void atomic_set_release(atomic_t *p,int next) { atomic_store_explicit(p,next,memory_order_release); }
__attribute__((noreturn)) static void panic(const char *fmt,...) { (void)fmt; longjmp(escape,1); }
struct list_head { struct list_head *next, *prev; };
struct gro_list { struct list_head list; int count; };
struct gro_node { unsigned long bitmask; struct gro_list hash[8]; };
struct napi_struct { struct list_head poll_list; struct gro_node gro; unsigned long state; int list_owner; };
struct rteth_ctrl;
struct rteth_rx_info { struct rteth_ctrl *ctrl; struct napi_struct napi; int id,slot; void *skb; atomic_t diag_rx_owner; unsigned long diag_polls[2],diag_zero_budget; };
struct net_device { const char *name; };
struct rteth_ctrl { struct net_device *dev; struct rteth_rx_info rx_info[2]; };
""" + helpers + r"""
int main(void) {
    struct rteth_ctrl *ctrl=calloc(1,sizeof(*ctrl));
    struct net_device dev={.name="test"};
    struct rteth_rx_info *ri=&ctrl->rx_info[0];
    ctrl->dev=&dev; ri->ctrl=ctrl;
    for (int i=0;i<8;i++) {
        struct list_head *head=&ri->napi.gro.hash[i].list;
        head->next=head; head->prev=head;
    }
    gro_diag=true;
    rteth_gro_diag_enter(ri,0);
    assert(!atomic_read(&ri->diag_rx_owner) && ri->diag_zero_budget==1);
    cpu=0; rteth_gro_diag_enter(ri,64);
    assert(atomic_read(&ri->diag_rx_owner)==1);
    if (!setjmp(escape)) { cpu=1; rteth_gro_diag_enter(ri,64); abort(); }
    assert(atomic_read(&ri->diag_rx_owner)==1);
    cpu=0; rteth_gro_diag_exit(ri,64);
    assert(!atomic_read(&ri->diag_rx_owner));
    /* Models a legal poll on another CPU after the old owner releases SCHED. */
    cpu=1; rteth_gro_diag_enter(ri,64);
    assert(atomic_read(&ri->diag_rx_owner)==2);
    rteth_gro_diag_exit(ri,64);
    assert(ri->diag_polls[0]==1 && ri->diag_polls[1]==1);
    free(ctrl); return 0;
}
"""
        with tempfile.TemporaryDirectory() as td:
            src, exe = Path(td) / 'owner.c', Path(td) / 'owner'
            src.write_text(c)
            subprocess.run(['gcc', '-std=gnu11', '-Wall', '-Wextra', '-Werror', '-fsanitize=address,undefined', str(src), '-o', str(exe)], check=True)
            subprocess.run([str(exe)], check=True, env={**os.environ, 'ASAN_OPTIONS': 'detect_leaks=0'})

    def test_bucket_checker_with_injected_corruption(self):
        text = (ROOT / 'openwrt/patches/300-45-net-rteth-gro-diagnostics.patch').read_text()
        added = '\n'.join(x[1:] for x in text.splitlines() if x.startswith('+') and not x.startswith('+++'))
        helper = added[added.index('static bool rteth_gro_diag_bad_node'):added.index('/* END host-checked')]
        c = r'''
#include <stdbool.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <assert.h>
#define PAGE_SIZE 4096
#define IS_ALIGNED(p, a) (!((p) & ((a)-1)))
#define READ_ONCE(x) (x)
struct list_head { struct list_head *next, *prev; };
struct gro_list { struct list_head list; int count; };
struct rteth_ctrl { struct list_head poll_list; struct gro_list hash[8]; char rest[256]; };
''' + helper + r'''
static void init(struct gro_list *b, struct list_head *n, int count) {
    struct list_head *h = &b->list;
    h->next = count ? &n[0] : h;
    h->prev = count ? &n[count-1] : h;
    b->count = count;
    for (int i=0; i<count; i++) {
        n[i].prev = i ? &n[i-1] : h;
        n[i].next = i+1<count ? &n[i+1] : h;
    }
}
int main(void) {
    struct rteth_ctrl *ctrl = calloc(1, sizeof(*ctrl));
    struct list_head *n = calloc(9, sizeof(*n));
    struct gro_list *b = &ctrl->hash[0];
    const void *bad = NULL;
#define CHECK(bit, reason) do { const char *r=rteth_gro_diag_bucket(ctrl,b,bit,&bad); assert(r && !strcmp(r,reason)); } while(0)
    for (int i=0; i<=8; i++) { init(b,n,i); assert(!rteth_gro_diag_bucket(ctrl,b,!!i,&bad)); }
    init(b,n,9); CHECK(true,"cycle-or-overfull");
    init(b,n,2); b->count=1; CHECK(true,"count");
    init(b,n,1); CHECK(false,"bitmask");
    init(b,n,0); CHECK(true,"bitmask");
    init(b,n,0); b->count=-1; CHECK(false,"count");
    init(b,n,2); n[1].prev=&b->list; CHECK(true,"prev-link");
    init(b,n,2); b->list.prev=&b->list; CHECK(true,"tail-link");
    init(b,n,2); n[1].next=&n[0]; CHECK(true,"prev-link");
    init(b,n,1); n[0].next=NULL; CHECK(true,"non-skb-node");
    init(b,n,1); b->list.next=(void *)1; CHECK(true,"non-skb-node");
    init(b,n,1); b->list.next=(void *)((uintptr_t)n+1); CHECK(true,"non-skb-node");
    init(b,n,1); b->list.next=&ctrl->poll_list; CHECK(true,"non-skb-node");
    init(b,n,1); n[0].next=&ctrl->poll_list; CHECK(true,"non-skb-node");
    init(b,n,1); n[0].next=&ctrl->hash[1].list; CHECK(true,"non-skb-node");
    free(n); free(ctrl); return 0;
}
'''
        with tempfile.TemporaryDirectory() as td:
            src, exe = Path(td) / 'check.c', Path(td) / 'check'
            src.write_text(c)
            subprocess.run(['gcc', '-std=gnu11', '-Wall', '-Wextra', '-Werror', '-fsanitize=address,undefined', str(src), '-o', str(exe)], check=True)
            subprocess.run([str(exe)], check=True, env={**os.environ, "ASAN_OPTIONS": "detect_leaks=0"})


if __name__ == '__main__':
    unittest.main()
