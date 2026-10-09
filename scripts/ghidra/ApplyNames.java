// ApplyNames.java -- apply a names ledger (*.sym) to the loaded program.
//
// Input lines: "<name>\t0x<va>"  ('#' comments and blank lines skipped).
//   - VA is a function entry (or a gap with code): rename the function; if no
//     function exists there but the bytes disassemble, create one.
//   - otherwise: create a data label.
// Only FUN_/thunk_FUN_/DAT_/default names are overwritten; curated names stay.
// A name already used elsewhere gets a "_<va>" suffix instead of failing.
//
// Usage (run on a scratch COPY of the project; changes are saved to the copy):
//   analyzeHeadless <dir> <proj> -process loader.bin -noanalysis \
//     -scriptPath scripts/ghidra -postScript ApplyNames.java a.sym b.sym \
//     -postScript DecompileAll.java out.c
// @category awto
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.address.AddressSpace;
import ghidra.program.model.listing.Function;
import ghidra.program.model.symbol.SourceType;
import ghidra.program.model.symbol.Symbol;
import ghidra.program.model.symbol.SymbolTable;
import java.io.BufferedReader;
import java.io.FileReader;

public class ApplyNames extends GhidraScript {
    @Override
    public void run() throws Exception {
        int ren = 0, made = 0, lab = 0, skip = 0, bad = 0;
        AddressSpace sp = currentProgram.getAddressFactory().getDefaultAddressSpace();
        SymbolTable st = currentProgram.getSymbolTable();
        for (String path : getScriptArgs()) {
            BufferedReader br = new BufferedReader(new FileReader(path));
            String line;
            while ((line = br.readLine()) != null) {
                line = line.trim();
                if (line.isEmpty() || line.startsWith("#")) continue;
                String[] p = line.split("\t");
                if (p.length < 2) { bad++; continue; }
                String name = p[0].trim();
                long va;
                try { va = Long.decode(p[1].trim()); } catch (Exception e) { bad++; continue; }
                Address a = sp.getAddress(va);
                if (currentProgram.getMemory().getBlock(a) == null) { bad++; continue; }
                Function f = getFunctionAt(a);
                if (f == null && (va & 3) == 0 && looksLikeText(va)) {
                    // gap the analyzer missed: (re)disassemble and create the function
                    if (getInstructionAt(a) == null) {
                        if (getDataAt(a) != null) clearListing(a, a.add(3));
                        disassemble(a);
                    }
                    try { f = createFunction(a, name); } catch (Exception e) { f = null; }
                    if (f != null) { made++; continue; }
                }
                if (f != null) {
                    String cur = f.getName();
                    if (cur.equals(name)) continue;
                    if (!(cur.startsWith("FUN_") || cur.startsWith("thunk_FUN_")
                            || f.getSymbol().getSource() == SourceType.DEFAULT)) { skip++; continue; }
                    if (rename(f, name)) ren++; else skip++;
                } else {
                    Symbol s = st.getPrimarySymbol(a);
                    if (s == null || s.getName().startsWith("DAT_")
                            || s.getSource() == SourceType.DEFAULT) {
                        createLabel(a, name, true, SourceType.IMPORTED);
                        lab++;
                    } else skip++;
                }
            }
            br.close();
        }
        println("ApplyNames: renamed=" + ren + " created=" + made + " labels=" + lab
                + " skipped=" + skip + " bad=" + bad);
    }

    // Text lives below the data section start; avoid creating functions in .rodata/.data.
    private boolean looksLikeText(long va) {
        return va >= 0x83f00000L && va < 0x83fb3c00L;
    }

    private boolean rename(Function f, String name) throws Exception {
        try {
            f.setName(name, SourceType.IMPORTED);
            return true;
        } catch (Exception e) {
            try {
                f.setName(name + "_" + Long.toHexString(f.getEntryPoint().getOffset() & 0xffffffffL),
                          SourceType.IMPORTED);
                return true;
            } catch (Exception e2) {
                println("rename failed " + name + " @ " + f.getEntryPoint() + ": " + e2.getMessage());
                return false;
            }
        }
    }
}
