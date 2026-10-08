import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;
import ghidra.program.model.symbol.Reference;
import ghidra.program.model.symbol.ReferenceManager;
import ghidra.program.model.symbol.Symbol;
import ghidra.program.model.symbol.SymbolIterator;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.LinkedHashSet;
import java.util.Set;

/*
 * DiagSocketAudit -- find and decompile the functions in `diag` that use the
 * socket-server API, so the listener loop and the shell handoff are visible.
 *
 * For each target import name it collects every matching symbol (external,
 * thunk, or PLT stub), walks references to it, resolves the containing caller
 * function, and decompiles each unique caller. Seeing bind/listen/accept proves
 * the agent; the accept-loop caller shows the port and the dup2(sock,0/1/2) +
 * execve handoff that serves a shell despite the fake /dev/console.
 *
 * Run:
 *   analyzeHeadless private/ghidra <project> -process diag \
 *     -postScript DiagSocketAudit.java <out.c> [import ...]
 * Default imports: bind listen accept accept4 dup2 execve socket
 * Output: the .c given as the first arg (keep under private/ghidra/; vendor
 * decompilation is not published).
 */
public class DiagSocketAudit extends GhidraScript {
    private static final String[] DEFAULT_TARGETS = {
        "bind", "listen", "accept", "accept4", "dup2", "execve", "socket"
    };

    @Override
    protected void run() throws Exception {
        String[] args = getScriptArgs();
        if (args.length < 1) {
            throw new IllegalArgumentException("Output file required");
        }
        String[] targets = args.length > 1
            ? java.util.Arrays.copyOfRange(args, 1, args.length)
            : DEFAULT_TARGETS;

        ReferenceManager refs = currentProgram.getReferenceManager();
        Set<Function> callers = new LinkedHashSet<>();
        StringBuilder report = new StringBuilder("/* DiagSocketAudit */\n");

        for (String name : targets) {
            Set<Address> sinks = new LinkedHashSet<>();
            SymbolIterator syms = currentProgram.getSymbolTable().getSymbols(name);
            while (syms.hasNext()) {
                Symbol sym = syms.next();
                sinks.add(sym.getAddress());
                Function f = getFunctionAt(sym.getAddress());
                if (f != null && f.isThunk()) {
                    sinks.add(f.getEntryPoint());
                }
            }
            int n = 0;
            for (Address sink : sinks) {
                for (Reference ref : refs.getReferencesTo(sink)) {
                    Function caller = getFunctionContaining(ref.getFromAddress());
                    if (caller != null) {
                        callers.add(caller);
                        n++;
                    }
                }
            }
            report.append(String.format("/* %-10s: %d symbol(s), %d call site(s) */%n",
                name, sinks.size(), n));
        }

        if (callers.isEmpty()) {
            report.append("/* no callers of any target import found -- "
                + "either diag uses no socket API, or dynamic symbols were not "
                + "imported (re-run analyzeHeadless with analysis enabled) */\n");
        }

        DecompInterface decompiler = new DecompInterface();
        try {
            if (!decompiler.openProgram(currentProgram)) {
                throw new IllegalStateException(decompiler.getLastMessage());
            }
            for (Function caller : callers) {
                DecompileResults result = decompiler.decompileFunction(caller, 120, monitor);
                report.append("\n/* ").append(caller.getName()).append(" @ ")
                    .append(caller.getEntryPoint()).append(" */\n");
                if (result.decompileCompleted() && result.getDecompiledFunction() != null) {
                    report.append(result.getDecompiledFunction().getC());
                } else {
                    report.append("/* decompile failed: ")
                        .append(result.getErrorMessage()).append(" */\n");
                }
            }
        } finally {
            decompiler.dispose();
        }
        Files.writeString(Path.of(args[0]), report.toString());
    }
}
