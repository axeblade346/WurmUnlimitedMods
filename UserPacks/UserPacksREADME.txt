User Packs 1.0 - the WurmLauncher\userpacks folder for the normal (default branch) game client
==============================================================================================

Please contact Axeblade for any bugs:
  axeblade346 on the Sklotopolis forums
  axeblade on the Wurm modding discord.

What it does
  The beta branch of Wurm Unlimited loads every .jar in WurmLauncher\userpacks as a resource pack
  (texture packs, model packs, the upscaled UP_ packs ...). The normal branch does not. This mod
  adds that to the normal client, doing exactly what the beta client does:
    * every .jar in WurmLauncher\userpacks is loaded when the game starts, in front of the game's
      own packs (graphics.jar, sound.jar ...), so its mappings.txt replaces theirs;
    * each pack is put first in name order, so when two packs change the same thing, the one whose
      name comes last in the alphabet wins (the same as on the beta client);
    * the folder is made if it is not there.
  On the beta client, which loads userpacks itself, the mod sees that and does nothing - so it can
  stay installed when you switch branches.

Install (needs Ago's client mod loader)
  Copy into WurmLauncher:
    WurmLauncher\mods\userpacks.properties
    WurmLauncher\mods\userpacks\userpacks.jar
  Put packs in WurmLauncher\userpacks and start the game. The game's console log
  (PlayerFiles\console.<player>.log) has a "Loaded user pack <name>" line for each one.

Server packs
  Packs a server sends (the serverpacks mod) work as before; user packs are loaded at game start,
  server packs when you connect.

Files
  mods\userpacks.properties, mods\userpacks\userpacks.jar   the mod
  Source code: https://github.com/axeblade346/WurmUnlimitedMods (UserPacks folder)
