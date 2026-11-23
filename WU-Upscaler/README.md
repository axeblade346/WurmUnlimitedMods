# WU Upscaler

Upscales Wurm Unlimited's textures 2× with AI (Real-ESRGAN) into small resource packs, one per
section of the game's mappings.txt, for `WurmLauncher\userpacks`. You run it from a page in your
browser that shows progress and CPU, RAM, GPU and video memory use.

- Reads graphics.jar and pmk.jar from your own game (found through Steam).
- One `UP_<folder>_<section>.jar` per section. Each holds its mappings.txt lines, the models,
  properties.xml, animations and upscaled textures, with the game's folder layout.
- `.dds` stays `.dds` with mipmaps; largest size is 4096×4096.
- Kept as they are: icon sheets and screen pictures (`gui`, `TutorialImages`), icons under 64×64,
  dye masks and player face parts.
- Resumable: stop it any time and start again.

**Needs:** Windows, Python 3.9+ (packages install themselves), 15-25 GB free space, and a client
that loads userpacks. That's either the beta branch, or the normal branch with the
[UserPacks](../UserPacks) mod. On the normal branch the page warns you; choose to upscale anyway.

**Download:** the `WU-Upscaler` zip on the [Releases](https://github.com/axeblade346/WurmUnlimitedMods/releases) page.
Full instructions and change history: [README.txt](README.txt).
