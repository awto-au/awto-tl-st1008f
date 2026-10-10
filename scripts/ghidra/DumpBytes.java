// DumpBytes — print the memory-block map and N bytes at each given address.
// Run: analyzeHeadless private/ghidra <proj> -process <bin> -noanalysis -readOnly \
//        -postScript DumpBytes.java <out.txt> <addr>:<nbytes> ...
// Output stays in private/ (vendor-derived).
import ghidra.app.script.GhidraScript;
import ghidra.program.model.mem.MemoryBlock;
import java.io.PrintWriter;

public class DumpBytes extends GhidraScript {
    @Override
    public void run() throws Exception {
        String[] a = getScriptArgs();
        PrintWriter out = new PrintWriter(a[0]);
        for (MemoryBlock b : currentProgram.getMemory().getBlocks())
            out.printf("BLOCK %s %s-%s init=%b%n", b.getName(), b.getStart(), b.getEnd(), b.isInitialized());
        for (int i = 1; i < a.length; i++) {
            String[] p = a[i].split(":");
            long va = Long.decode(p[0]);
            int n = Integer.parseInt(p[1]);
            StringBuilder sb = new StringBuilder();
            for (int k = 0; k < n; k++) {
                try {
                    sb.append(String.format("%02x ", getByte(toAddr(va + k)) & 0xff));
                } catch (Exception e) { sb.append("?? "); }
            }
            out.printf("0x%08x: %s%n", va, sb);
        }
        out.close();
    }
}
