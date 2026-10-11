// DecompileRefsTo — decompile every function that references a symbol (by name) or an address (0x...).
// Args: <out.c> <name|0xaddr> ... Each function is preceded by `// FUNC <va> <name> ref=<target>`.
// Used by scripts/vendor_nic_decompile.py (`ref` mode): who reads a board-config global or a callback slot.
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;
import ghidra.program.model.symbol.Reference;
import ghidra.program.model.symbol.Symbol;
import java.io.PrintWriter;
import java.util.LinkedHashMap;
import java.util.Map;

public class DecompileRefsTo extends GhidraScript {
    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        if (args.length < 2) {
            println("usage: DecompileRefsTo <out.c> <name|0xaddr> ...");
            return;
        }
        Map<Function, String> funcs = new LinkedHashMap<>();
        for (int i = 1; i < args.length; i++) {
            Address a = null;
            if (args[i].startsWith("0x")) {
                a = toAddr(args[i]);
            } else {
                for (Symbol s : currentProgram.getSymbolTable().getSymbols(args[i])) { a = s.getAddress(); break; }
            }
            if (a == null) { println("no symbol " + args[i]); continue; }
            for (Reference r : getReferencesTo(a)) {
                Function f = getFunctionContaining(r.getFromAddress());
                if (f != null && !funcs.containsKey(f)) funcs.put(f, args[i]);
            }
        }
        PrintWriter out = new PrintWriter(args[0]);
        DecompInterface di = new DecompInterface();
        di.openProgram(currentProgram);
        // per-function bound: a MIPS function decompiles in seconds; 60 s caps a pathological CFG
        for (Map.Entry<Function, String> e : funcs.entrySet()) {
            Function f = e.getKey();
            out.printf("%n// FUNC 0x%08x %s ref=%s%n", f.getEntryPoint().getOffset(), f.getName(), e.getValue());
            DecompileResults r = di.decompileFunction(f, 60, monitor);
            if (r != null && r.decompileCompleted() && r.getDecompiledFunction() != null) {
                out.println(r.getDecompiledFunction().getC());
            } else {
                out.println("// <decompile failed: " + (r == null ? "null" : r.getErrorMessage()) + ">");
            }
        }
        out.close();
        di.dispose();
        println("DecompileRefsTo: " + funcs.size() + " functions -> " + args[0]);
    }
}
