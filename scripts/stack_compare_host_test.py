#!/usr/bin/env python3
"""Host-only safety checks for the stack comparison runner."""

import contextlib
import io
import json
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import nat_bench as bench
import st1008_ramload as ramload
import stack_compare as compare
import stack_normalize as normalize
import stack_results as results


class IrqSafetyTest(unittest.TestCase):
    def test_upstream_cpu1_is_refused_before_push(self):
        for flags in ([], ["--napi", "irq1"]):
            with self.subTest(flags=flags):
                args = ["stack_normalize.py", "--stack", "A", *flags]
                with mock.patch.object(sys, "argv", args), mock.patch.object(normalize, "push") as push:
                    with contextlib.redirect_stderr(io.StringIO()) as stderr:
                        with self.assertRaises(SystemExit) as exc:
                            normalize.main()
                self.assertEqual(exc.exception.code, 2)
                self.assertIn("300-18", stderr.getvalue())
                push.assert_not_called()

    def test_upstream_cpu0_is_allowed(self):
        args = ["stack_normalize.py", "--stack", "A", "--napi", "irq0", "--dry-run"]
        with mock.patch.object(sys, "argv", args), mock.patch.object(normalize, "push") as push, \
             mock.patch.object(normalize, "run_remote", return_value=""), mock.patch.object(normalize, "log"):
            self.assertEqual(normalize.main(), 0)
        push.assert_called_once()

    def test_upstream_snapshot_does_not_change_affinity(self):
        args = ["stack_normalize.py", "--stack", "A", "--snapshot-only", "--dry-run"]
        with mock.patch.object(sys, "argv", args), mock.patch.object(normalize, "push") as push, \
             mock.patch.object(normalize, "run_remote", return_value=""), mock.patch.object(normalize, "log"):
            self.assertEqual(normalize.main(), 0)
        push.assert_not_called()

    def test_comparison_runs_a_and_warns_about_mismatch(self):
        args = SimpleNamespace(stacks="B,A,C", clocks="common", profile="clean")
        with mock.patch.object(compare, "CTRL"), mock.patch.object(compare, "run_stack", return_value=True) as run_stack, \
             mock.patch.object(compare, "log") as log:
            self.assertEqual(compare.run_all(args), 0)
        self.assertEqual([call.args[0] for call in run_stack.call_args_list], ["B", "A", "C"])
        self.assertIn("NOT CONTROLLED", log.call_args_list[0].args[0])

    def test_comparison_still_runs_b_and_c(self):
        args = SimpleNamespace(stacks="B,C", clocks="common", profile="clean")
        with mock.patch.object(compare, "CTRL"), mock.patch.object(compare, "run_stack", return_value=True) as run_stack, \
             mock.patch.object(compare, "log"):
            self.assertEqual(compare.run_all(args), 0)
        self.assertEqual([call.args[0] for call in run_stack.call_args_list], ["B", "C"])

    def test_runner_selects_and_checks_irq_affinity(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(compare, "CTRL", Path(tmp)), \
             mock.patch.object(compare, "sh", return_value=(0, "snapshot -> test")), mock.patch.object(compare, "log"):
            for stack, expected in (("A", "irq0"), ("B", "irq1"), ("C", "irq1")):
                self.assertEqual(compare.normalise(stack, Path(tmp)), 0)
                argv = compare.sh.call_args.args[0]
                self.assertEqual(argv[argv.index("--napi") + 1], expected)
        self.assertIsNone(normalize.irq_readback_failure({"irq_affinity": "irq24 00000001"}, "irq0"))
        self.assertIn("expected 1", normalize.irq_readback_failure({"irq_affinity": "irq24 2"}, "irq0"))
        self.assertIn("expected 1", normalize.irq_readback_failure({}, "irq0"))

    def test_gate_refuses_irq_mismatch_and_normalisation_failures(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(compare, "log"):
            root = Path(tmp)
            a = {"irq_affinity": "irq24 1", "napi": "irq0", "normalise_failures": ""}
            b = {"irq_affinity": "irq24 2", "napi": "irq1", "normalise_failures": ""}
            (root / "stack_snapshot-A.json").write_text(json.dumps(a))
            (root / "stack_snapshot-B.json").write_text(json.dumps(b))
            ok, header = compare.gate(["A", "B"], root, write=False)
            self.assertFalse(ok)
            self.assertIn("irq_affinity", "\n".join(header))
            (root / "stack_snapshot-B.json").write_text(json.dumps({**a, "normalise_failures": "FAIL offloads"}))
            ok, header = compare.gate(["A", "B"], root, write=False)
            self.assertFalse(ok)
            self.assertIn("normalisation failures: B", "\n".join(header))

    def test_failed_normalisation_prevents_benchmark(self):
        with mock.patch.object(compare, "normalise", return_value=1), mock.patch.object(compare, "Session") as session, \
             mock.patch.object(compare, "log"):
            self.assertFalse(compare.run_stack("A", "common", "clean", SimpleNamespace(no_boot=True)))
        session.assert_not_called()

    def test_boot_requires_clean_log_and_reads_uboot_clock_on_a(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "tmp").mkdir()
            console = root / "console.log"
            console.write_text("bb00e220: 00030626\n")
            commands = {
                "echo root": "root",
                "cut -d. -f1 /proc/uptime": "25",
            }

            def ssh(cmd, *_args):
                return commands.get(cmd, "6.18.60\nBogoMIPS: 513.63\n" +
                                    "devmem: not found\n" * 4 + "52000\n")

            def boot_sh(_argv, *_args):
                with console.open("a") as out:
                    out.write("bb00e220: 00030626\n")
                return 0, ""

            with mock.patch.object(compare, "ROOT", root), mock.patch.object(compare, "CONSOLE", console), \
                 mock.patch.object(compare, "CTRL", root), mock.patch.object(compare, "BOOTS", root / "boots.jsonl"), \
                 mock.patch.object(compare, "sh", side_effect=boot_sh), mock.patch.object(compare, "ssh", side_effect=ssh), \
                 mock.patch.object(compare, "alive", return_value=True), \
                 mock.patch.object(compare.subprocess, "run", return_value=SimpleNamespace(returncode=0)), \
                 mock.patch.object(compare, "log"):
                self.assertTrue(compare.boot("A", "common", "clean"))
                compare.sh.return_value = (1, "boot log UNKNOWN")
                compare.sh.side_effect = None
                self.assertFalse(compare.boot("A", "common", "clean"))
            boots = [json.loads(line) for line in (root / "boots.jsonl").read_text().splitlines()]
            self.assertTrue(boots[0]["e220_ok"])
            self.assertFalse(boots[1]["ok"])

    def test_result_table_labels_irq_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rowfile = root / "rows.jsonl"
            rowfile.write_text("\n".join(json.dumps({"stack": s, "clk": "common", "profile": "clean",
                                                      "cell": "nat", "ok": True, "mbps": 1})
                                         for s in ("A", "B")) + "\n")
            snaps = root / "snap-common"
            snaps.mkdir()
            for stack, affinity in (("A", "irq24 1"), ("B", "irq24 2")):
                (snaps / f"stack_snapshot-{stack}.json").write_text(json.dumps({"irq_affinity": affinity}))
            with mock.patch.object(results, "ROWS", rowfile), contextlib.redirect_stdout(io.StringIO()) as output:
                results.main()
            self.assertIn("NOT CONTROLLED", output.getvalue())
            self.assertIn("A `irq24 1`; B `irq24 2`", output.getvalue())
            self.assertIn("CPU percentages are not comparable", output.getvalue())


class ComparisonPlanTest(unittest.TestCase):
    def test_directly_connected_hardware_routing_is_only_planned_for_b(self):
        plans = {stack: "\n".join(compare.plan(stack, "common", "clean")[1]) for stack in "ABC"}
        self.assertIn("eligible gateway routes can still be hardware routed", plans["A"])
        self.assertIn("l3on-tcp-P4-fwd", plans["B"])
        self.assertNotIn("l3on-tcp-P4-fwd", plans["A"])
        self.assertNotIn("l3on-tcp-P4-fwd", plans["C"])
        self.assertIn("not scheduled (B only)", plans["C"])


class NormalizationSnapshotTest(unittest.TestCase):
    def test_targeted_sysctls_exclude_deprecated_neighbor_entry(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            entries = {
                "net/core/skb_defer_max": "128",
                "net/ipv4/tcp_comp_sack_slack_ns": "10000",
                "net/netfilter/nf_conntrack_buckets": "8192",
                "net/ipv6/neigh/default/base_reachable_time": "30000",
            }
            for name, value in entries.items():
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(value + "\n")
            command = normalize.SNAP_SYSCTL.replace("/proc/sys/", f"{root}/")
            output = subprocess.run(["sh", "-c", command], check=True, capture_output=True, text=True).stdout
        self.assertIn("net.core.skb_defer_max = 128", output)
        self.assertIn("net.ipv4.tcp_comp_sack_slack_ns = 10000", output)
        self.assertIn("net.netfilter.nf_conntrack_buckets = 8192", output)
        self.assertNotIn("base_reachable_time", output)

    def test_targeted_sysctl_read_failures_are_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "net/core/skb_defer_max"
            path.parent.mkdir(parents=True)
            path.write_text("128\n")
            command = "cat() { echo permission-denied >&2; return 1; }; " + \
                      normalize.SNAP_SYSCTL.replace("/proc/sys/", f"{root}/")
            output = subprocess.run(["sh", "-c", command], check=True, capture_output=True, text=True).stdout
        self.assertIn("FAIL sysctl read net/core/skb_defer_max: permission-denied", output)

    def test_snapshot_only_fails_on_sysctl_read_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = ["stack_normalize.py", "--stack", "A", "--snapshot-only", "--snap-dir", tmp]
            output = "@@sysctl\nFAIL sysctl read net/core/skb_defer_max: permission-denied\n"
            with mock.patch.object(sys, "argv", args), mock.patch.object(normalize, "run_remote", return_value=output), \
                 mock.patch.object(normalize, "log"):
                self.assertEqual(normalize.main(), 1)
            snap = json.loads((Path(tmp) / "stack_snapshot-A.json").read_text())
            self.assertIn("permission-denied", snap["normalise_failures"])

    def test_readback_requires_pinned_settings_and_effective_gro(self):
        features = ("\n".join(("generic-receive-offload: on", "generic-segmentation-offload: off [requested on]",
                               "rx-gro-list: on", "rx-udp-gro-forwarding: off", "tx-nocache-copy: off",
                               "tx-checksumming: off")))
        snap = {"sysctl": "\n".join(f"{key} = {value}" for key, value in normalize.SYSCTLS),
                "ethtool_k_eth0": features, "ethtool_k_lan1": features}
        self.assertEqual(normalize.settings_readback_failures(snap, []), [])
        self.assertEqual(normalize.settings_readback_failures(snap, ["tx=off"]), [])
        wrong = {**snap, "ethtool_k_lan1": features.replace("generic-receive-offload: on",
                                                          "generic-receive-offload: off [requested on]")}
        self.assertIn("lan1 gro", "\n".join(normalize.settings_readback_failures(wrong, [])))
        wrong = {**snap, "ethtool_k_eth0": features.replace("off [requested on]", "off")}
        self.assertIn("eth0 gso", "\n".join(normalize.settings_readback_failures(wrong, [])))
        wrong = {**snap, "sysctl": snap["sysctl"].replace("nf_conntrack_buckets = 8192",
                                                          "nf_conntrack_buckets = 63488")}
        self.assertIn("nf_conntrack_buckets", "\n".join(normalize.settings_readback_failures(wrong, [])))

    def test_gate_recovers_historical_hashes_and_reports_bucket_differences(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(compare, "log"):
            root = Path(tmp)
            legacy = {"v_musl": "musl 1.2.6 @@sha_pinned\nabc  iperf3", "irq_affinity": "irq24 2",
                      "sysctl": "net.netfilter.nf_conntrack_buckets = 8192"}
            current = {"v_musl": "musl 1.2.6", "sha_pinned": "abc  iperf3", "irq_affinity": "irq24 2",
                       "sysctl": "net.netfilter.nf_conntrack_buckets = 8192"}
            (root / "stack_snapshot-A.json").write_text(json.dumps(current))
            (root / "stack_snapshot-B.json").write_text(json.dumps(legacy))
            self.assertTrue(compare.gate(["A", "B"], root, write=False)[0])
            current["sysctl"] = "net.netfilter.nf_conntrack_buckets = 63488"
            (root / "stack_snapshot-A.json").write_text(json.dumps(current))
            ok, header = compare.gate(["A", "B"], root, write=False)
            self.assertFalse(ok)
            self.assertIn("net.netfilter.nf_conntrack_buckets", "\n".join(header))
            current["ethtool_k_eth0"] = "tls-hw-record: off [fixed]"
            (root / "stack_snapshot-A.json").write_text(json.dumps(current))
            ok, header = compare.gate(["A", "B"], root, write=False)
            self.assertFalse(ok)
            self.assertIn("tls-hw-record", "\n".join(header))

    def test_pinned_upload_allows_at_least_thirty_seconds(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "lib").mkdir()
            (root / "tool").write_bytes(b"tool")
            result = SimpleNamespace(returncode=0, stderr=b"")
            with mock.patch.object(normalize, "TOOLS", root), \
                 mock.patch.object(normalize, "PINNED", [("tool", "tool", "755")]), \
                 mock.patch.object(normalize.subprocess, "run", return_value=result) as run, \
                 mock.patch.object(normalize, "log"):
                normalize.push(SimpleNamespace(ip="192.0.2.1", dry_run=False))
            self.assertGreaterEqual(run.call_args.kwargs["timeout"], 30)


class SharedEnvironmentTest(unittest.TestCase):
    def test_setup_refuses_namespace_with_active_process(self):
        def host(cmd, **_kwargs):
            if cmd == ["ip", "netns", "list"]:
                return "natlan\nnatwan\n"
            if cmd == ["ip", "netns", "pids", "natlan"]:
                return "1234\n"
            return ""

        with mock.patch.object(bench, "host", side_effect=host), mock.patch.object(bench, "sw") as sw, \
             mock.patch.object(bench, "log"):
            self.assertEqual(bench.setup(), 2)
        sw.assert_not_called()

    def test_generator_only_teardown_does_not_touch_switch(self):
        names = {"natlan", "natwan"}

        def host(cmd, **_kwargs):
            if cmd == ["ip", "netns", "list"]:
                return "\n".join(sorted(names))
            if cmd[:3] == ["ip", "netns", "del"]:
                names.discard(cmd[3])
            return ""

        with mock.patch.object(bench, "host", side_effect=host) as remote, mock.patch.object(bench, "sw") as sw, \
             mock.patch.object(bench, "log"):
            self.assertEqual(bench.teardown(generator_only=True), 0)
        sw.assert_not_called()
        self.assertIn(mock.call(["ip", "netns", "del", "natlan"], check=False), remote.call_args_list)
        self.assertIn(mock.call(["ip", "netns", "del", "natwan"], check=False), remote.call_args_list)

    def test_teardown_reports_state_left_after_failed_deletion(self):
        def host(cmd, **_kwargs):
            return "natlan\n" if cmd == ["ip", "netns", "list"] else ""

        with mock.patch.object(bench, "host", side_effect=host), mock.patch.object(bench, "log"):
            self.assertEqual(bench.teardown(generator_only=True), 1)

    def test_forward_server_is_one_shot_owned_and_bounded(self):
        server = mock.Mock(returncode=0)
        server.poll.return_value = None
        server.communicate.return_value = (None, "")
        client = SimpleNamespace(stdout='{"end": {}}', stderr="")
        with mock.patch.object(bench.subprocess, "Popen", return_value=server) as spawn, \
             mock.patch.object(bench, "host_run", return_value=client), mock.patch.object(bench.time, "sleep"):
            self.assertEqual(bench.iperf("natwan", "10.99.2.2", "natlan", 10, 4, False, None, None), {"end": {}})
        remote = spawn.call_args.args[0][-1]
        self.assertIn("timeout 25 iperf3 -s -1 -B 10.99.2.2", remote)
        self.assertNotIn("-D", remote)
        server.communicate.assert_called_once()

    def test_ipv6_server_is_bounded_and_client_uses_source_address(self):
        server = mock.Mock(returncode=0)
        server.poll.return_value = None
        server.communicate.return_value = (None, "")
        client = SimpleNamespace(stdout='{"end": {}}', stderr="")
        with mock.patch.object(bench.subprocess, "Popen", return_value=server) as spawn, \
             mock.patch.object(bench, "host_run", return_value=client) as run, mock.patch.object(bench.time, "sleep"):
            self.assertEqual(bench.iperf("natwan", "fd99:22::5", "natlan", 10, 4, True, None, None,
                                         ipv6=True, src_ip="fd99:11::5"), {"end": {}})
        self.assertIn("timeout 25 iperf3 -6 -s -1 -B fd99:22::5", spawn.call_args.args[0][-1])
        self.assertEqual(run.call_args.args[0],
                         ["nice", "-n", "19", "ip", "netns", "exec", "natlan", "iperf3", "-6",
                          "-c", "fd99:22::5", "-B", "fd99:11::5", "-t", "10", "-P", "4", "-J", "-O", "2", "-R"])
        server.communicate.assert_called_once()

    def test_ipv6_run_reports_iperf_error_without_result(self):
        with mock.patch.object(bench, "sw"), mock.patch.object(bench, "snap", side_effect=[{}, {}]), \
             mock.patch.object(bench, "iperf", return_value={"error": "connection failed"}) as iperf, \
             mock.patch.object(bench, "summarize") as summarize, mock.patch.object(bench, "log") as log:
            self.assertEqual(bench.v6_run(10, 4, True, reverse=True), 1)
        iperf.assert_called_once_with("natwan", "fd99:2::2", "natlan", 10, 4, True, None, None,
                                      ipv6=True, src_ip="fd99:1::2")
        summarize.assert_not_called()
        self.assertIn("connection failed", log.call_args.args[0])

    def test_forward_server_is_reaped_on_client_failure(self):
        server = mock.Mock(returncode=0)
        server.poll.return_value = None
        server.communicate.return_value = (None, "")
        with mock.patch.object(bench.subprocess, "Popen", return_value=server), \
             mock.patch.object(bench, "host_run", side_effect=SystemExit("client failed")), mock.patch.object(bench.time, "sleep"):
            with self.assertRaisesRegex(SystemExit, "client failed"):
                bench.iperf("natwan", "10.99.2.2", "natlan", 10, 1, False, None, None)
        server.communicate.assert_called_once()

    def test_forward_server_bind_failure_does_not_run_client(self):
        server = mock.Mock(returncode=1)
        server.poll.return_value = 1
        server.communicate.return_value = (None, "address in use")
        with mock.patch.object(bench.subprocess, "Popen", return_value=server), \
             mock.patch.object(bench, "host_run") as client, mock.patch.object(bench.time, "sleep"):
            with self.assertRaisesRegex(SystemExit, "address in use"):
                bench.iperf("natwan", "10.99.2.2", "natlan", 10, 1, False, None, None)
        client.assert_not_called()
        server.communicate.assert_called_once()

    def test_invalid_local_server_pid_is_not_signalled(self):
        with mock.patch.object(bench, "sw", return_value="1") as sw:
            with self.assertRaisesRegex(SystemExit, "invalid local iperf3 PID"):
                bench.stop_local_iperf()
        self.assertEqual(sw.call_count, 1)

    def test_teardown_only_unloads_a_loaded_pktgen(self):
        for loaded in (False, True):
            with self.subTest(loaded=loaded), \
                 mock.patch.object(bench, "sw", side_effect=["loaded" if loaded else "", ""]) as sw:
                bench.stop_pktgen()
            self.assertEqual(sw.call_count, 2 if loaded else 1)
            if loaded:
                self.assertEqual(sw.call_args.args[0], "rmmod pktgen")

    def test_daemon_restart_requests_socket_shutdown(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "tmp/logs").mkdir(parents=True)
            sock_path, pid_path = root / "daemon.sock", root / "daemon.pid"
            pid_path.write_text("123")
            listener = socket.socket(socket.AF_UNIX)
            listener.bind(str(sock_path))
            listener.listen()
            received = []

            def serve():
                with listener, listener.accept()[0] as conn:
                    received.append(json.loads(conn.recv(1024)))
                    conn.sendall(b'{"ok":true}\n')
                sock_path.unlink()
                pid_path.unlink()

            thread = threading.Thread(target=serve)
            thread.start()
            with mock.patch.object(ramload, "ROOT", root), mock.patch.object(ramload, "SOCK", sock_path), \
                 mock.patch.object(ramload, "DAEMON_PID", pid_path), \
                 mock.patch.object(ramload.subprocess, "Popen", side_effect=lambda *a, **k: sock_path.touch()) as spawn, \
                 mock.patch.object(ramload, "log"):
                ramload.restart_daemon()
            thread.join(timeout=3)
            self.assertFalse(thread.is_alive())
            self.assertEqual(received, [{"op": "quit"}])
            spawn.assert_called_once()

    def test_tftp_timeout_stops_only_its_privileged_parent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "image.bin").write_bytes(b"test")
            server = mock.Mock(pid=12345)
            server.wait.side_effect = [subprocess.TimeoutExpired("tftpd", 3), -15]
            con = mock.Mock()
            con.run.side_effect = SystemExit("transfer failed")
            with mock.patch.object(ramload, "TFTP_ROOT", root), mock.patch.object(ramload, "ensure_server_ip"), \
                 mock.patch.object(ramload.subprocess, "Popen", return_value=server), \
                 mock.patch.object(ramload.subprocess, "run") as run, mock.patch.object(ramload, "log"):
                with self.assertRaisesRegex(SystemExit, "transfer failed"):
                    ramload.tftp(con, "image.bin", 0x81000000)
            run.assert_called_once_with(["sudo", "-n", "kill", "-TERM", "12345"], check=True, timeout=5)

    def test_stop_session_leaves_unrelated_process_running(self):
        sleeper = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"], start_new_session=True)
        other = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"], start_new_session=True)
        try:
            compare.stop_session(sleeper.pid)
            sleeper.wait(timeout=5)
            self.assertIsNone(other.poll())
        finally:
            for proc in (sleeper, other):
                if proc.poll() is None:
                    proc.terminate()
                    proc.wait(timeout=5)


if __name__ == "__main__":
    unittest.main()
