package userpacks;

import java.io.File;
import java.util.Arrays;
import java.util.logging.Level;
import java.util.logging.Logger;

import org.gotti.wurmunlimited.modloader.classhooks.HookManager;
import org.gotti.wurmunlimited.modloader.interfaces.Initable;
import org.gotti.wurmunlimited.modloader.interfaces.Versioned;
import org.gotti.wurmunlimited.modloader.interfaces.WurmClientMod;

import javassist.ClassPool;
import javassist.CtClass;
import javassist.CtConstructor;
import javassist.NotFoundException;

/**
 * User Packs: the WurmLauncher/userpacks folder of the beta client, for the normal (default branch) client.
 *
 * Every .jar in WurmLauncher/userpacks is loaded as a resource pack in front of the game's own packs,
 * the same way the beta client does it (each pack placed first, in name order, so with two packs
 * changing the same thing the one whose name comes last in the alphabet wins).
 * On the beta client, which loads userpacks itself, this mod does nothing.
 */
public class UserPacksMod implements WurmClientMod, Initable, Versioned {
    static final Logger LOG = Logger.getLogger("UserPacks");
    static final File DIR = new File("userpacks");

    @Override
    public void init() {
        try {
            ClassPool cp = HookManager.getInstance().getClassPool();
            CtClass res = cp.get("com.wurmonline.client.resources.Resources");
            try {
                res.getDeclaredMethod("loadUserPacks");
                LOG.info("[UserPacks] this game client loads userpacks itself (beta branch): User Packs does nothing");
                return;
            } catch (NotFoundException normalClient) {
                // the default branch: add it
            }
            // after the game's own packs are set up: the same code the beta client runs (JarPack / Pack.init are
            // package-private, so this is compiled into Resources itself)
            String code = "{ java.io.File[] fs = userpacks.UserPacksMod.jars();"
                    + "  for (int i = 0; i < fs.length; i++) {"
                    + "    try {"
                    + "      com.wurmonline.client.resources.JarPack p = new com.wurmonline.client.resources.JarPack(fs[i]);"
                    + "      p.init(this);"
                    + "      this.packs.add(0, p);"
                    + "      System.out.println(\"Loaded user pack \" + p.getName());"
                    + "    } catch (java.io.IOException e) {"
                    + "      System.out.println(\"Failed to load user pack \" + fs[i] + \": \" + e);"
                    + "    }"
                    + "  } }";
            for (CtConstructor c : res.getDeclaredConstructors()) c.insertAfter(code);
            LOG.info("[UserPacks] WurmLauncher\\userpacks will be loaded");
        } catch (Throwable t) {
            LOG.log(Level.SEVERE, "[UserPacks] could not add userpacks", t);
        }
    }

    /** the .jar files in WurmLauncher/userpacks, in name order (none if Mod Profiles has userpacks off for this player) */
    public static File[] jars() {
        try {
            if (!DIR.isDirectory()) DIR.mkdir();
            if (!allowedByModProfiles()) return new File[0];
            File[] fs = DIR.listFiles((d, n) -> n.toLowerCase().endsWith(".jar") && new File(d, n).isFile());
            if (fs == null) return new File[0];
            Arrays.sort(fs, (a, b) -> a.getName().compareToIgnoreCase(b.getName()));
            return fs;
        } catch (Throwable t) {
            LOG.log(Level.WARNING, "[UserPacks] could not read the userpacks folder", t);
            return new File[0];
        }
    }

    /** Mod Profiles can switch userpacks off per player */
    static boolean allowedByModProfiles() {
        try {
            Class<?> c = Class.forName("modprofiles.Profiles");
            return (Boolean) c.getMethod("userPacksAllowed").invoke(null);
        } catch (ClassNotFoundException notInstalled) {
            return true;
        } catch (Throwable t) {
            return true;
        }
    }

    @Override
    public String getVersion() {
        return "1.0";
    }
}
