// DecompileStringUsers — decompile every function that references a defined string containing a needle.
// Args: <out.c> <needle> [needle ...]. Each function is preceded by `// FUNC <va> <name> needle=<s>`.
// Used by scripts/vendor_nic_decompile.py (`str` mode) to find the code behind XML keys / log strings.
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.program.model.listing.Data;
import ghidra.program.model.listing.Function;
import ghidra.program.model.symbol.Reference;
import java.io.PrintWriter;
import java.util.LinkedHashMap;
import java.util.Map;

public class DecompileStringUsers extends GhidraScript {
    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        if (args.length < 2) {
            println("usage: DecompileStringUsers <out.c> <needle> ...");
            return;
        }
        Map<Function, String> funcs = new LinkedHashMap<>();
        for (Data d : currentProgram.getListing().getDefinedData(true)) {
            if (monitor.isCancelled()) break;
            Object v = d.getValue();
            if (!(v instanceof String)) continue;
            for (int i = 1; i < args.length; i++) {
                if (!((String) v).contains(args[i])) continue;
                for (Reference r : getReferencesTo(d.getAddress())) {
                    Function f = getFunctionContaining(r.getFromAddress());
                    if (f != null && !funcs.containsKey(f)) funcs.put(f, args[i]);
                }
            }
        }
        PrintWriter out = new PrintWriter(args[0]);
        DecompInterface di = new DecompInterface();
        di.openProgram(currentProgram);
        // per-function bound: a MIPS function decompiles in seconds; 60 s caps a pathological CFG
        for (Map.Entry<Function, String> e : funcs.entrySet()) {
            Function f = e.getKey();
            out.printf("%n// FUNC 0x%08x %s needle=%s%n", f.getEntryPoint().getOffset(), f.getName(), e.getValue());
            DecompileResults r = di.decompileFunction(f, 60, monitor);
            if (r != null && r.decompileCompleted() && r.getDecompiledFunction() != null) {
                out.println(r.getDecompiledFunction().getC());
            } else {
                out.println("// <decompile failed: " + (r == null ? "null" : r.getErrorMessage()) + ">");
            }
        }
        out.close();
        di.dispose();
        println("DecompileStringUsers: " + funcs.size() + " functions -> " + args[0]);
    }
}
