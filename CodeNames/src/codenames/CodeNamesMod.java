package codenames;

import java.util.Properties;
import javassist.ClassPool;
import javassist.CtClass;
import org.gotti.wurmunlimited.modloader.classhooks.HookManager;
import org.gotti.wurmunlimited.modloader.interfaces.Configurable;
import org.gotti.wurmunlimited.modloader.interfaces.Initable;
import org.gotti.wurmunlimited.modloader.interfaces.PreInitable;
import org.gotti.wurmunlimited.modloader.interfaces.Versioned;
import org.gotti.wurmunlimited.modloader.interfaces.WurmClientMod;
import org.gotti.wurmunlimited.modsupport.console.ConsoleListener;
import org.gotti.wurmunlimited.modsupport.console.ModConsole;

/**
 * Code Names - adds the game's own code name of whatever is under the mouse to the hover
 * tooltip, e.g. img.texture.cave.marble for a marble wall or model.tool.pickaxe for an item.
 * Client side only: it shows names the client already has and sends nothing to the server.
 */
public class CodeNamesMod implements WurmClientMod, PreInitable, Initable, Configurable, Versioned {

    @Override public String getVersion() { return "1.3"; }

    @Override
    public void configure(Properties p) {
        CodeNames.on = Boolean.parseBoolean(p.getProperty("showCodeNames", "true").trim());
        CodeNames.files = Boolean.parseBoolean(p.getProperty("showFiles", "true").trim());
        CodeNames.all = Boolean.parseBoolean(p.getProperty("showAll", "false").trim());
    }

    @Override
    public void preInit() {
        ClassPool pool = HookManager.getInstance().getClassPool();
        // items, creatures, walls, fences, floors, roofs, bridges: the game already makes these
        // lines but keeps them for developer servers only
        try {
            CtClass pd = pool.get("com.wurmonline.client.renderer.PickData");
            pd.getDeclaredMethod("addDevText", new CtClass[]{pool.get("java.lang.String"), CtClass.booleanType})
              .insertBefore("codenames.CodeNames.dev(this.text, $1);");
            CodeNames.log("hook PickData.addDevText: ok");
        } catch (Throwable e) { CodeNames.log("hook PickData.addDevText FAILED: " + e); }
        // ground tiles (grass, rock, roads, trees, bushes)
        try {
            CtClass tp = pool.get("com.wurmonline.client.renderer.TilePicker");
            tp.getDeclaredMethod("getHoverDescription").insertAfter(
                "codenames.CodeNames.tile($1, this.world.getNearTerrainBuffer().getTileType(this.x, this.y),"
              + " this.world.getNearTerrainBuffer().getData(this.x, this.y));");
            CodeNames.log("hook TilePicker.getHoverDescription: ok");
        } catch (Throwable e) { CodeNames.log("hook TilePicker FAILED: " + e); }
        // cave walls, floors and ceilings: the name comes from the tile next to the wall
        try {
            CtClass cw = pool.get("com.wurmonline.client.renderer.cave.CaveWallPicker");
            cw.getDeclaredMethod("getHoverDescription").insertAfter(
                "codenames.CodeNames.cave($1, this.world.getCaveBuffer().getTileType(this.xNeighbor, this.yNeighbor));");
            CodeNames.log("hook CaveWallPicker.getHoverDescription: ok");
        } catch (Throwable e) { CodeNames.log("hook CaveWallPicker FAILED: " + e); }
    }

    @Override
    public void init() {
        try {
            ModConsole.addConsoleListener(new ConsoleListener() {
                @Override public boolean handleInput(String line, Boolean silent) { return CodeNames.console(line); }
            });
        } catch (Throwable e) { CodeNames.log("console command FAILED: " + e); }
    }
}
