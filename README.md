# Wurm Unlimited Mods and Tools

Tools and client mods for **Wurm Unlimited** by Axeblade.

**Downloads:** see [Releases](https://github.com/axeblade346/WurmUnlimitedMods/releases). Each project
has its own zip with everything needed to run it. This repository holds the source code.

| Project | What it is | Needs |
|---|---|---|
| [WU-Upscaler](WU-Upscaler) | Upscales the game's textures 2× (AI) into resource packs for `WurmLauncher\userpacks`, controlled from a page in your browser. | Windows, Python 3.9+, the beta client or the UserPacks mod |
| [WOM-Converter](WOM-Converter) | Converts the game's `.wom` models to `.obj` / `.glb` for Blender and back, with skeletons, animations, mappings.txt variants and texture upscaling. Includes the WOM Viewer. | Python 3.8+, numpy, Pillow |
| [WOM-Viewer](WOM-Viewer) | Model viewer in your browser for the game's models, animations, items and player outfits. Reads your own graphics.jar; works offline. | A browser (Python 3.8+ for the launcher) |
| [CodeNames](CodeNames) | Client mod: the hover tooltip shows the code name of what is under the mouse (`img.texture.cave.marble`, `model.rune.magranon.rift crystal.cherrywood.`) and the file it was loaded from. | Ago's client mod loader |
| [UserPacks](UserPacks) | Client mod: loads `WurmLauncher\userpacks` on the normal (non-beta) client, the same way the beta client does. | Ago's client mod loader |

## Installing

- **Tools** (WU-Upscaler, WOM-Converter, WOM-Viewer): unzip anywhere outside the game folder and
  follow the README in the zip.
- **Mods** (CodeNames, UserPacks): need [Ago's client mod loader](https://github.com/ago1024/WurmClientModLauncher).
  Copy the zip's `mods` folder into `WurmLauncher`.

## Building the mods from source

Compile against the jars of your own game (Java 8):

```
set WL=C:\Program Files (x86)\Steam\steamapps\common\Wurm Unlimited\WurmLauncher
set CP=%WL%\client.jar;%WL%\common.jar;%WL%\javassist.jar;%WL%\lib\client-modlauncher-parent-0.10.1.jar
javac -source 8 -target 8 -d build -cp "%CP%" CodeNames\src\codenames\*.java
jar cf codenames.jar -C build codenames
```

Use `UserPacks\src\userpacks\*.java` and `userpacks.jar` / `-C build userpacks` the same way.

## Licence

**All rights reserved.** You may use the release files for your own Wurm Unlimited play. Copying,
changing, reusing or redistributing the code needs my written permission first. See [LICENSE](LICENSE),
which also lists the parts made by others (Real-ESRGAN model weights, three.js) and their licences.

## Contact

Bugs, questions and permission requests: **Axeblade**, axeblade346 on the Sklotopolis forums,
axeblade on the Wurm modding Discord, or an issue on this repository.

## Credits

- BDEW, for his update of the original Code Club AB .wom converter (https://github.com/bdew-wurm/WOM-Converter),
  which the WOM tools build on.
- Warlander, for the WOM Model Viewer and DeedPlanner 3 that the viewer is modelled on.
- Xintao Wang and contributors, for Real-ESRGAN.
- Ago, for the Wurm Unlimited client mod loader.

Wurm Unlimited is owned by Code Club AB. This project is not affiliated with Code Club AB.
