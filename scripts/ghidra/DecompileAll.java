// DecompileAll — dump every function in the loaded program as decompiled C,
// each preceded by `// FUNC <va> <name> size=<n>`, to the file named in
// scriptArgs[0]. One headless pass = the whole binary, no per-address calls and
// no project-lock contention from parallel runs.
//
// Run (read-only, no DB changes):
//   analyzeHeadless private/ghidra stock-loader-mapped -process loader.bin \
//     -readOnly -postScript DecompileAll.java <out.c>
//
// Output stays in private/ (vendor-code decompilation is not published).
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.FunctionManager;
import java.io.PrintWriter;

public class DecompileAll extends GhidraScript {
    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        if (args.length < 1) {
            println("usage: DecompileAll <out.c>");
            return;
        }
        PrintWriter out = new PrintWriter(args[0]);
        DecompInterface di = new DecompInterface();
        di.openProgram(currentProgram);
        FunctionManager fm = currentProgram.getFunctionManager();
        int n = 0, ok = 0;
        // timeout per function: decompilation of one MIPS function is seconds;
        // 60 s is ~20x the worst seen and bounds a pathological CFG. On expiry
        // the function is emitted as a stub line so the dump stays complete.
        int PERFUNC_TIMEOUT_S = 60;
        for (Function f : fm.getFunctions(true)) {
            if (monitor.isCancelled()) break;
            n++;
            long va = f.getEntryPoint().getOffset();
            long sz = f.getBody().getNumAddresses();
            out.printf("%n// FUNC 0x%08x %s size=%d%n", va, f.getName(), sz);
            try {
                DecompileResults r = di.decompileFunction(f, PERFUNC_TIMEOUT_S, monitor);
                if (r != null && r.decompileCompleted()
                        && r.getDecompiledFunction() != null) {
                    out.println(r.getDecompiledFunction().getC());
                    ok++;
                } else {
                    out.println("// <decompile failed: "
                                + (r == null ? "null" : r.getErrorMessage()) + ">");
                }
            } catch (Exception e) {
                out.println("// <exception: " + e.getMessage() + ">");
            }
            if (n % 100 == 0) { out.flush(); println("decompiled " + n); }
        }
        out.flush();
        out.close();
        di.dispose();
        println("DecompileAll done: " + ok + "/" + n + " functions -> " + args[0]);
    }
}
