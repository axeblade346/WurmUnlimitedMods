WU Upscaler 1.6.1 - upscales Wurm Unlimited's textures 2x into packs for WurmLauncher\userpacks
==========================================================================================

What it does
  * Reads the mappings.txt inside graphics.jar (and pmk.jar) and makes one small .jar pack per
    section of mappings.txt (the "# Horses -----" lines) and top folder, e.g.
        UP_creatures_Horses.jar, UP_trees_Oak.jar, UP_player_2048.jar, UP_pmk_models.jar
    (UP_ marks them as upscaled packs in userpacks)
  * Each pack holds its own mappings.txt (the lines of that section, unchanged), the .wom models,
    their properties.xml and animations, and the upscaled textures - all with the full folder
    structure of the game (creatures/horse/... stays creatures/horse/...).
  * Textures are upscaled 2x with AI (largest 4096x4096). .dds files stay .dds with the same
    compression and mipmaps when the original had them.
  * Textures in 256/512/1024/2048 folders (the player textures): each folder gets the real art of
    the folder above it (the 2048 art goes into the 1024 folder, and so on) and only the 2048
    textures are AI-upscaled, to 4096.
  * Packs you don't want are simply not copied: you pick what goes into userpacks yourself.

Needs
  * A client that loads userpacks: the BETA branch of Wurm Unlimited (in Steam: right-click
    Wurm Unlimited > Properties > Betas and choose the beta branch), or the normal branch with the
    UserPacks mod (https://github.com/axeblade346/WurmUnlimitedMods). The page checks the installed
    client and warns you if it can't load userpacks; with UserPacks installed, choose to upscale anyway.
  * Windows with Python 3.9 or newer (python.org; tick "Add python.exe to PATH" when installing).
    The Python packages it needs (numpy, pillow, psutil) are installed by the tool itself.
  * For the fast GPU engine: any NVIDIA, AMD or Intel graphics card with a current driver.
    The "Install GPU engine" button downloads Real-ESRGAN (ncnn Vulkan, about 50 MB) once.
    Without it the CPU engine is used (the same kind of AI model, but many times slower).
  * 15-25 GB free on the drive with the staging folder.

Step by step
  1. Unzip this folder anywhere (not inside the game folder) and double-click Start_Upscaler.bat.
     A black window opens (keep it open) and the page opens in your browser.
  2. graphics.jar: the page finds it through Steam (button "Use this graphics.jar"), or use Browse...
     It is in  ...\steamapps\common\Wurm Unlimited\WurmLauncher\packs\graphics.jar
  3. Staging folder: Browse... to a folder on a drive with plenty of space.
  4. Press "Install GPU engine" once, then "Test GPU" to see that it works.
  5. Press "Read mappings.txt": the Packs list shows every pack that will be made. Untick the
     folders you don't want (or leave them all ticked).
  6. Press "Start / Resume". The console shows every texture, a status line every minute with
     the time, CPU, RAM, GPU and VRAM use, and the bar at the top shows how far it is and the
     time left. A full run takes hours.
  7. Finished packs appear in <staging folder>\jars as they are made ("Open finished packs").
     Copy the ones you want into WurmLauncher\userpacks ("Open userpacks") and start the game.

Stopping and carrying on
  Stop, closing the window, a crash or a power cut are all safe. Textures are written as
  name.part.dds and packs as name.jar.part and only get their real name when complete. Start /
  Resume removes half-written files, checks every finished texture is whole, skips finished packs
  (and remakes any whose contents no longer match), and carries on.
  If graphics.jar changes (a game update), the next run reads mappings.txt again by itself.

Files
  Start_Upscaler.bat     starts it
  wu_upscaler.py         the web page / server (http://127.0.0.1:5110, only reachable from this PC)
  upscale_run.py         does the work (can also be run by hand: python upscale_run.py -h)
  page.html              the page
  womtex.py, womfast.py, womprogress.py, womlib.py   upscaling engine (same as in the WOM converter)
  realesr-general-*.npz  the CPU AI model (Real-ESRGAN, BSD-3 licence: REALESRGAN_LICENSE.txt)
  upscaler_settings.json your settings (made on first use)

1.1
  * Some GPUs (seen on an RTX 3050) return black pictures for flat or dark textures. These were
    already caught and redone on the CPU; now they are first tried again on the GPU with small
    tiles, one at a time, and only then on the CPU.
  * The colour tables in the root of graphics.jar (suncolor, skycolor, ambientColor, gradient)
    are kept as they are: the game reads them by position, upscaling adds nothing.
  * Pictures of 16x16 or smaller get a plain resize instead of AI.
  * *_nor textures (normal maps) get a plain resize, like the other normal maps.

1.2
  * The check for black GPU results no longer flags dark textures (peat, cave slate, ore veins):
    the AI deepens near-black a little, which counted as "damaged". Only areas that were clearly
    lit and came back black, or a picture that came back much darker overall, count now.

1.3
  * One pack at a time: each pack is finished (upscaled and packed) before the next one starts,
    in the order of mappings.txt.
  * The Packs list updates itself while it works, and open folders stay open.

1.4
  * Checks that the installed game client can use userpacks (the beta branch) and says so on the
    page; Start asks before upscaling for a client without userpacks.

1.5
  * Fix for a crash in the game: models with a dye mask (the <mask> lines in properties.xml, such
    as u_cm.dds for the unicorn, cart_m.dds for carts) now get their mask in the pack. The masks
    are kept at their original size.
  * Pictures smaller than 64x64 (icons) are kept as they are ("Keep as they are" on the page).
  * Pack names start with UP_. Packs made by an earlier version (without UP_) are removed from the
    jars folder and made again under the new name - remove the old ones from userpacks too.
  * The next run reads mappings.txt again and repacks everything; textures already upscaled are
    reused, so it is much quicker than the first run.

1.5.1
  * Fix: a run could stop with "PermissionError: Access is denied ... progress.json" when the page
    (or a virus scanner) was reading the progress file at the moment it was updated. It now tries
    again for a few seconds, and the progress file can never stop a run.

1.6
  * The gui and TutorialImages folders are no longer upscaled. Their pictures are icon sheets and
    screen pictures that the game cuts or shows by pixel size, so upscaled copies made the
    inventory and toolbelt icons too large. The UP_gui_* and UP_TutorialImages_* packs are removed
    from the jars folder on the next run - remove them from userpacks too if they are still there.
    All other packs are kept as they are (nothing is upscaled or packed again).

1.6.1
  * Fix for player faces (missing eyes, mouth inside the nose): the face parts in
    player/textures/<256-2048>/Face (eyes, iris, eyebrows, nose, chin, complexion, facial hair...)
    are kept at their original size. The game paints them at fixed spots on the face, sized by
    the folder they are in. For sharper faces use the game's own face texture resolution setting.
    The next run puts the original face parts back and repacks only the UP_player_* packs that
    hold them - copy those packs to userpacks again.
