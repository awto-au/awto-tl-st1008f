// DecompileMatching — decompile every function whose name matches a Java regex.
// Args: <out.c> <regex>. Each function is preceded by `// FUNC <va> <name> size=<n>`.
// Used by scripts/vendor_nic_decompile.py on large stripped-but-dynsym binaries.
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.program.model.listing.Function;
import java.io.PrintWriter;
import java.util.regex.Pattern;

public class DecompileMatching extends GhidraScript {
    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        if (args.length < 2) {
            println("usage: DecompileMatching <out.c> <regex>");
            return;
        }
        Pattern p = Pattern.compile(args[1]);
        PrintWriter out = new PrintWriter(args[0]);
        DecompInterface di = new DecompInterface();
        di.openProgram(currentProgram);
        // per-function bound: a MIPS function decompiles in seconds; 60 s caps a pathological CFG
        int timeoutS = 60, n = 0;
        for (Function f : currentProgram.getFunctionManager().getFunctions(true)) {
            if (monitor.isCancelled()) break;
            if (!p.matcher(f.getName()).matches()) continue;
            n++;
            out.printf("%n// FUNC 0x%08x %s size=%d%n", f.getEntryPoint().getOffset(),
                       f.getName(), f.getBody().getNumAddresses());
            DecompileResults r = di.decompileFunction(f, timeoutS, monitor);
            if (r != null && r.decompileCompleted() && r.getDecompiledFunction() != null) {
                out.println(r.getDecompiledFunction().getC());
            } else {
                out.println("// <decompile failed: " + (r == null ? "null" : r.getErrorMessage()) + ">");
            }
        }
        out.close();
        di.dispose();
        println("DecompileMatching: " + n + " functions -> " + args[0]);
    }
}
