import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.program.model.listing.Function;
import ghidra.program.model.address.Address;
import java.nio.file.Files;
import java.nio.file.Path;

public class TraceLoader extends GhidraScript {
    @Override
    protected void run() throws Exception {
        String[] args = getScriptArgs();
        DecompInterface decompiler = new DecompInterface();
        StringBuilder output = new StringBuilder();
        try {
            if (!decompiler.openProgram(currentProgram)) {
                throw new IllegalStateException(decompiler.getLastMessage());
            }
            for (int i = 1; i < args.length; i++) {
                String[] target = args[i].split("=", 2);
                Address address = toAddr(target[0]);
                Function function = getFunctionContaining(address);
                if (target.length == 2 && target[1].startsWith("exact_") &&
                    (function == null || !function.getEntryPoint().equals(address))) {
                    if (function != null) {
                        currentProgram.getFunctionManager().removeFunction(function.getEntryPoint());
                    }
                    disassemble(address);
                    function = currentProgram.getFunctionManager().createFunction(
                        target[1], address,
                        new ghidra.program.model.address.AddressSet(address),
                        ghidra.program.model.symbol.SourceType.USER_DEFINED);
                }
                if (function == null) {
                    for (int back = 0; back < 4096; back += 4) {
                        Address candidate = address.subtract(back);
                        int word = getInt(candidate);
                        if ((word >>> 16) == 0x27bd && (word & 0xffff) > 0x8000) {
                            disassemble(candidate);
                            function = createFunction(candidate, null);
                            break;
                        }
                    }
                }
                if (function == null) {
                    throw new IllegalStateException("No function at " + address);
                }
                if (target.length == 2 && target[1].startsWith("exact_") &&
                    !function.getEntryPoint().equals(address)) {
                    throw new IllegalStateException("Wrong exact entry: " + function.getEntryPoint());
                }
                if (target.length == 2) {
                    function.setName(target[1],
                        ghidra.program.model.symbol.SourceType.USER_DEFINED);
                }
                DecompileResults result = decompiler.decompileFunction(function, 120, monitor);
                if (!result.decompileCompleted() || result.getDecompiledFunction() == null) {
                    throw new IllegalStateException(function + ": " + result.getErrorMessage());
                }
                output.append("\n/* Candidate mapping; ").append(function.getEntryPoint())
                    .append(" */\n").append(result.getDecompiledFunction().getC());
            }
            Files.writeString(Path.of(args[0]), output.toString());
        } finally {
            decompiler.dispose();
        }
    }
}
