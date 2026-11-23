package codenames;

import java.util.List;
import com.wurmonline.client.renderer.PickData;
import com.wurmonline.mesh.Tiles;

public final class CodeNames {
    static volatile boolean on = true;      // showCodeNames
    static volatile boolean files = true; 
    static volatile boolean all = false;    // showAll: every hidden developer line, unfiltered

    private CodeNames() {}

    static void log(String s) { System.out.println("[CodeNames] " + s); }

    private static boolean isCode(String s) {
        String t = s.trim();
        if (t.startsWith("model:")) t = t.substring(6).trim();
        // a code name is one dotted word: model.decoration.statue, img.texture.cave.marble,
        // or whatever name a server's custom item uses (no spaces, not a file)
        if (t.indexOf('@') >= 0 || t.startsWith("com.") || t.startsWith("java.") || t.startsWith("org.")) return false;  // Java object names
        // the game's own names can have spaces: model.rune.magranon.rift crystal.cherrywood.
        if ((t.startsWith("model.") || t.startsWith("img.") || t.startsWith("sound.")) && !isFile(t)) return true;
        return !t.isEmpty() && Character.isLetter(t.charAt(0)) && t.indexOf('.') > 0 && !t.matches(".*\\s.*") && !isFile(t);
    }

    private static boolean isFile(String s) {
        String t = s.toLowerCase();
        return t.contains(".wom") || t.contains(".dds") || t.contains(".png") || t.contains(".jpg")
            || t.contains(".xsi") || t.contains(".dae");
    }

    private static void add(List<String> text, String s) {
        if (s == null || s.isEmpty()) return;
        String t = s.trim();
        if (t.startsWith("model:")) t = t.substring(6).trim();
        if (!text.contains(t)) text.add(t);
    }

    /** called for every developer line the game makes for the hovered object */
    public static void dev(List<String> text, String s) {
        try {
            if (!on || s == null || text == null) return;
            if (all) { if (!text.contains(s)) text.add(s); return; }
            if (isCode(s) || (files && isFile(s))) add(text, s);
        } catch (Throwable ignored) { }
    }

    private static void once(PickData pd, String s) {
        if (s == null || s.isEmpty()) return;
        List<String> text = pd.getText();
        if (text == null || !text.contains(s)) pd.addText(s);
    }

    public static void tile(PickData pd, Tiles.Tile t, byte data) {
        try {
            if (!on || t == null) return;
            once(pd, t.getTextureResource());
            if (t.isTree() || t.isBush()) {
                String m = t.getModelResourceName(data);
                once(pd, m);
            }
        } catch (Throwable ignored) { }
    }

    public static void cave(PickData pd, Tiles.Tile t) {
        try {
            if (on && t != null) once(pd, t.getTextureResource());
        } catch (Throwable ignored) { }
    }

    /** console: codenames [on|off|files on|files off] */
    static boolean console(String line) {
        if (line == null) return false;
        String[] a = line.trim().toLowerCase().split("\\s+");
        if (a.length == 0 || !(a[0].equals("codenames") || a[0].equals("cn"))) return false;
        if (a.length >= 2 && a[1].equals("on")) on = true;
        else if (a.length >= 2 && a[1].equals("off")) on = false;
        else if (a.length >= 3 && a[1].equals("files")) files = a[2].equals("on");
        else if (a.length >= 3 && a[1].equals("all")) all = a[2].equals("on");
        else if (a.length == 1) on = !on;
        log("code names " + (on ? "on" : "off") + ", files " + (files ? "on" : "off") + ", all " + (all ? "on" : "off")
            + "   (codenames on|off, codenames files on|off, codenames all on|off)");
        return true;
    }
}
