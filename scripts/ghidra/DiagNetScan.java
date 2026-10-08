import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.program.model.address.Address;
import ghidra.program.model.lang.Register;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.FunctionIterator;
import ghidra.program.model.listing.Instruction;
import ghidra.program.model.listing.InstructionIterator;
import ghidra.program.model.scalar.Scalar;
import ghidra.program.model.symbol.Reference;
import ghidra.program.model.symbol.ReferenceManager;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Arrays;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Set;

/*
 * DiagNetScan -- answer two questions about a Realtek SDK binary that the libc
 * import table cannot: (1) does it make RAW syscalls (bind/listen/accept via
 * `syscall`, bypassing the PLT)? (2) what calls socket/setsockopt/system, and
 * is any of it a network listener rather than an ioctl handle?
 *
 * Part A: every `syscall` instruction, with the constant last loaded into v0
 *         ($2) within the preceding 40 insns = the syscall number. MIPS o32:
 *         socket 4183, bind 4169, connect 4170, listen 4174, accept 4168.
 * Part B: thunk-aware callers of the target imports, decompiled.
 *
 * Run (project already analysed):
 *   analyzeHeadless private/ghidra stock-diag -process diag \
 *     -postScript DiagNetScan.java <out.c> [import ...]
 * Default imports: socket setsockopt system bind listen accept connect dup2 execve
 */
public class DiagNetScan extends GhidraScript {
    private static final String[] DEFAULTS = {
        "socket", "setsockopt", "system", "bind", "listen", "accept",
        "connect", "dup2", "execve"
    };

    @Override
    protected void run() throws Exception {
        String[] args = getScriptArgs();
        if (args.length < 1) throw new IllegalArgumentException("Output file required");
        Set<String> targets = new LinkedHashSet<>(Arrays.asList(
            args.length > 1 ? Arrays.copyOfRange(args, 1, args.length) : DEFAULTS));
        StringBuilder out = new StringBuilder("/* DiagNetScan */\n\n");

        // ---- Part A: raw syscall scan ----
        out.append("/* ===== raw syscall sites (v0 = o32 syscall number) ===== */\n");
        Register v0 = currentProgram.getRegister("v0");
        int syscalls = 0;
        InstructionIterator insns = currentProgram.getListing().getInstructions(true);
        while (insns.hasNext()) {
            Instruction in = insns.next();
            if (!"syscall".equals(in.getMnemonicString())) continue;
            syscalls++;
            long num = -1;
            Instruction p = in;
            for (int i = 0; i < 40 && p != null; i++) {
                p = p.getPrevious();
                if (p == null) break;
                boolean writesV0 = false;
                for (Object o : p.getResultObjects())
                    if (o instanceof Register && ((Register) o).equals(v0)) writesV0 = true;
                if (!writesV0) continue;
                Scalar s = null;
                for (int op = 0; op < p.getNumOperands(); op++) {
                    Scalar sc = p.getScalar(op);
                    if (sc != null) s = sc;
                }
                if (s != null) { num = s.getUnsignedValue(); break; }
                break; // v0 written by a non-constant op: give up this site
            }
            Function f = getFunctionContaining(in.getAddress());
            out.append(String.format("  syscall @ %s  v0=%s  in %s%n",
                in.getAddress(), num < 0 ? "?" : Long.toString(num),
                f != null ? f.getName() : "?"));
        }
        out.append(String.format("/* total syscall instructions: %d */%n%n", syscalls));

        // ---- Part B: thunk-aware callers of the target imports ----
        Set<Address> sinks = new LinkedHashSet<>();
        FunctionIterator fns = currentProgram.getFunctionManager().getFunctions(true);
        while (fns.hasNext()) {
            Function f = fns.next();
            Function t = f.isThunk() ? f.getThunkedFunction(true) : f;
            if (t != null && targets.contains(t.getName())) sinks.add(f.getEntryPoint());
            if (targets.contains(f.getName())) sinks.add(f.getEntryPoint());
        }
        ReferenceManager rm = currentProgram.getReferenceManager();
        Set<Function> callers = new LinkedHashSet<>();
        for (Address sink : sinks)
            for (Reference r : rm.getReferencesTo(sink)) {
                Function c = getFunctionContaining(r.getFromAddress());
                if (c != null) callers.add(c);
            }
        out.append(String.format("/* ===== %d import sink(s), %d caller function(s) ===== */%n",
            sinks.size(), callers.size()));

        DecompInterface dec = new DecompInterface();
        try {
            if (!dec.openProgram(currentProgram))
                throw new IllegalStateException(dec.getLastMessage());
            for (Function c : callers) {
                DecompileResults rr = dec.decompileFunction(c, 120, monitor);
                out.append("\n/* ").append(c.getName()).append(" @ ")
                   .append(c.getEntryPoint()).append(" */\n");
                out.append(rr.decompileCompleted() && rr.getDecompiledFunction() != null
                    ? rr.getDecompiledFunction().getC()
                    : "/* decompile failed: " + rr.getErrorMessage() + " */\n");
            }
        } finally { dec.dispose(); }
        Files.writeString(Path.of(args[0]), out.toString());
    }
}
