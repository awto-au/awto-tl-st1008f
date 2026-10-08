import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.FunctionIterator;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Arrays;
import java.util.HashSet;
import java.util.Set;

public class DecompileSelected extends GhidraScript {
    @Override
    protected void run() throws Exception {
        String[] args = getScriptArgs();
        if (args.length < 2) {
            throw new IllegalArgumentException("Output file and function names required");
        }
        Set<String> names = new HashSet<>(Arrays.asList(args).subList(1, args.length));
        DecompInterface decompiler = new DecompInterface();
        StringBuilder output = new StringBuilder();
        try {
            if (!decompiler.openProgram(currentProgram)) {
                throw new IllegalStateException(decompiler.getLastMessage());
            }
            FunctionIterator functions = currentProgram.getFunctionManager().getFunctions(true);
            while (functions.hasNext()) {
                Function function = functions.next();
                if (!names.remove(function.getName())) {
                    continue;
                }
                DecompileResults result = decompiler.decompileFunction(function, 60, monitor);
                if (!result.decompileCompleted() || result.getDecompiledFunction() == null) {
                    throw new IllegalStateException(function.getName() + ": " + result.getErrorMessage());
                }
                output.append("\n/* ").append(function.getName()).append(" @ ")
                    .append(function.getEntryPoint()).append(" */\n")
                    .append(result.getDecompiledFunction().getC());
            }
            if (!names.isEmpty()) {
                throw new IllegalStateException("Missing functions: " + names);
            }
            Files.writeString(Path.of(args[0]), output.toString());
        } finally {
            decompiler.dispose();
        }
    }
}
