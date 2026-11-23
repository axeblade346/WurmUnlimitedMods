# WOM ⇄ OBJ converter for Wurm Unlimited.

## Getting started (Windows)

**1. Install Python** (3.8 or newer; the newest is fine)
- Download it from the official site: https://www.python.org/downloads/
- During the install, tick **"Add python.exe to PATH"** if the installer shows it, so the `python`
  command works in a command window.
- The official guide, including what to do when `python` isn't found:
  https://docs.python.org/3/using/windows.html

**2. Open a command window in this folder**
- Easiest: open the WOM-Converter folder in File Explorer, click the address bar, type `cmd`, and
  press Enter. Command Prompt opens already in that folder.
- Or press **Windows key + R**, type `cmd` and press Enter (Command Prompt), or press
  **Windows key + X** and pick **Terminal** (PowerShell). Then go to the folder, e.g.
  `cd "C:\Tools\WOM-Converter"`.
- Microsoft's help: https://learn.microsoft.com/en-us/answers/questions/5637237/how-to-open-command-prompt-in-windows-11

**3. Install / update everything the tools need** (run again any time to update):

```
python -m pip install --upgrade pip numpy pillow
python wom_tool.py setup-gpu
```

- The first line installs or updates numpy and Pillow (and pip itself).
- The second downloads the GPU upscaling engine next to the tool, runs a test, and lists the GPUs it
  can use. It works on NVIDIA, AMD Radeon and Intel Arc cards. It's only needed for upscaling.
- If `python` isn't found, try `py` instead (`py -m pip install --upgrade pip numpy pillow`).
- The model viewer needs none of this: `wom_viewer.html` runs in your browser, and its launcher
  (`WOM Viewer.bat` / `wom_viewer.py`) needs only Python itself.

The Scripts are based on work done by BDEW as updates of the original CodeClubAB .wom converter
His work can be found at https://github.com/bdew-wurm/WOM-Converter

Also check out his other mods / tools
- https://github.com/bdew-wurm
- https://forum.wurmonline.com/index.php?/topic/136575-released-bdew-client-mods-new-mod-fishbuddy-updated-apr-09/
- https://forum.wurmonline.com/index.php?/topic/138254-released-bdew-server-mods-new-mod-fishy-tweaks-updated-apr-09/

WU Modding discord 14 Nov 2026

> **bdéw** 17:01 (UTC+2)
> i don't mind, you can do whatever with my code
> (mind you the code from code club doesn't have any license AFAIK, so the legal status of the whole thing is questionable)
>
> **Axeblade** 17:04 (UTC+2)
> Thank you and ye I also saw code clubs one is missing a license. I'll work under the "as long as its for Wurm unlimited" rule.

Model viewer (`wom_viewer.html`): Interface and viewing port inspired by DeedPlanner 3.

For modding Wurm Unlimited (single player or player-hosted servers) only.

Version and change history: `VERSION.txt` (or `python wom_tool.py --version`).

Files: `wom_tool.py` (the tool), `wom_viewer.py` + `WOM Viewer.bat` (viewer launcher), `womlib.py` (WOM reader/writer), `womgltf.py` (glTF/animation),
`womtex.py` (texture upscaling) and two `realesr-general-*.npz` model files. Keep them in one folder.
Needs Python 3.8+, numpy and Pillow 11.2 or newer: `python -m pip install --upgrade pip numpy pillow`
(see **Getting started** above).

## Commands

```
python wom_tool.py info    female_1_04.wom          # list meshes, textures, bones (or an animation's bones/length)
python wom_tool.py wom2obj female_1_04.wom          # -> .obj + .mtl + .womdata.json
python wom_tool.py obj2wom female_1_04.obj          # -> female_1_04_new.wom
```

**Keep the `.womdata.json` next to the `.obj`.** It holds what OBJ can't: skeleton, skin weights,
material settings and mesh order. Without it, `obj2wom` writes a static (unanimated) model.

## Model viewer (wom_viewer.html)

**Easiest:** double-click **`WOM Viewer.bat`** (Windows), or run `python wom_viewer.py` (same as `python wom_tool.py viewer`). It asks Steam where Wurm Unlimited is installed (any
Steam library, e.g. `C:\Program Files (x86)\Steam\steamapps\common\Wurm Unlimited\WurmLauncher\packs\graphics.jar`)
and opens the viewer with that `graphics.jar` already loaded. Keep its window open while you use the
viewer. If Steam doesn't know the game, it uses the jar from last time, or asks once with a file
picker; the choice is kept in `wom_viewer_settings.json`. `--jar "<path to graphics.jar>"` picks
another one.

You can also double-click `wom_viewer.html` (Chrome, Edge or Firefox; works offline). Nothing is
uploaded: the files are read on your own PC.

Header buttons:
- **Open game's .jar files**: pick `<game>\WurmLauncher\packs\graphics.jar`. It is read while still
  zipped: only its index at the start, then each file when a model needs it. Nothing is extracted.
  In Chrome and Edge the page remembers it: next time it loads by itself if the browser still allows
  it, otherwise **Reopen graphics.jar** loads it in one click. Firefox can't remember picked files;
  use `WOM Viewer.bat` there.
- **Open custom folder**: your converted or edited files, e.g. `player_obj` from `batch`. Its `.obj`
  models (with their `.mtl` and `.womdata.json`, so skeleton, skin and animations still work; a
  hair placed on the body by `wom2obj` is put back) and `.wom` models replace the game's where the
  path matches, and are marked **(CF)** in the Files list. A folder named `player_obj` stands for
  the game's `player` folder. Its `mappings.txt` or `mappings_matched.txt` is used on top of the
  game's (same key = yours wins), as are its armor.xml and properties.xml where the game has none.
- **Upscale folder**: the output of `upscale` (e.g. `player_upscaled`). Its textures (from its 2048
  folders, or the plain folders where there are none) become the **4096** choice of the Textures
  menu. A custom-folder texture that is only a copy of the game's doesn't hide the upscaled one.
- **Custom object**: a folder with new or replacing objects. A file named like a game file replaces
  it; a new hair named like the game's (`NewHair/femaleHair08.obj`, `male_hair06.wom`) is an extra
  choice in the Hair menu, and `ring…` / `…earring…` models are choices for the ring and earring slots.
  A `mappings.txt` inside it is used too, with paths inside that folder (a mod's
  `hair6.female = femaleHair07_new.wom` makes that the game's hair slot 6).
- The tick box switches the custom folder and custom objects off; ✕ removes them and the upscale folder.
- No mappings.txt button any more: it is found in the .jar and in your custom folder by itself.

Browse on the left:
- **Files**: every model (animations are only under Animations). (CF) = from your custom folder,
  (custom) = a custom object.
- **Items**: every mappings.txt item whose file is there. Items that reuse a model with other
  textures are marked ✦ and shown with their own textures and material values.
- **Animations**: click one to play it on the open character. The extra last frame the game's
  animations end with (it snaps back towards the T pose) is left out, so loops don't flash it.

**Compare** (header button) splits the view. The right side is what the header shows. The left
side has its own **files** (game .jar only, or game .jar + custom folder) and **texture size**
(256-2048, or 4096 from the upscale folder), e.g. left ".jar · 2048" against right "custom · 4096".
Pick **wipe** (drag the line) or **side by side**. Both sides share the camera, lights, outfit,
hair, dyes and the playing animation.

**Export** panel: **Picture (.png)**, **Animation (.gif)** and **Animation (.avi)** of what the view
shows (light markers left out, compare view included). Animations are recorded frame by frame:
the playing animation 3 times, at its speed, at the chosen frames per second and size. GIF is at
most 25 fps and 256 colours (480-640 wide keeps it small); AVI is Motion-JPEG (plays in Windows,
VLC and video editors).

Panels stay open or closed the way you left them, also between visits.

**Settings are kept per object** (outfit, hair, face, dyes, mount gear, animation, hidden meshes)
while you switch between models, also after closing the page. **Default** at the top of the right
panel resets the open object.

For any model you get the mesh list (bounding/picking boxes and LOD meshes are hidden), a
**Textures** resolution picker (256 to 2048), a screenshot button and wireframe mode. If mappings.txt
lists several items for the model, an **Item / variant** menu switches between them.

For **player characters** (female_1_04, Male_1_04, …) the viewer dresses the model the way the game
does:
- **Body texture**: nude, then the under-clothes (baseCloth), then each armour piece from armor.xml
  pasted into its body area (torso, UA, LA, legs, LL, hand, foot, tasset…), with the mesh variants
  armor.xml asks for (e.g. `torso06`). Pick pieces per slot under **Outfit**; kingdom designs
  (tabards) have a **design** menu.
- **Face**: the head meshes use a face texture built from mappings.txt. The head type
  (`upperFaceN` = `textures/<size>/Face/Default/<gender>/headType`, with the ears) is the base and
  has a see-through eye opening. The eye white and the iris (`eyeColorN`, **Default** or **HOTS**
  colours) go under it, the eye shape (`eyeTypeN`, `eyeShape` files: lids and lashes) on top, lined
  up by their openings. Complexion, nose, chin (`lh`), eye shape and eyebrows are placed where the
  game puts them (found from the game's own composed default faces in `textures/DefaultLoad`;
  on the 1024 head texture: nose and eye shape at 0,356, chin at 0,516, brows at 20,335,
  complexion at 0,356). With upscaled or edited textures, each face piece gets the same colour
  change the head had at that spot (compared with the game's own files), so the pieces blend as in
  the game. **Facial hair** (men): the stubble is painted on the face and the beards
  use the model's own beard meshes (`facialHair2-7Mesh`), with the hair colour. The hairline isn't
  offered (it is the game's bald look; choose hair under Character).
- **Hair**: the `hairN` / `hairN.female` slots from mappings.txt. Hair files are static meshes
  modelled around the **NullHelmet** bone, and are placed there (optional hair colour).
- **Mounts** (horse, hell horse, unicorn – each its own model): a **Mount gear** panel offers the gear
  meshes the model actually contains: barding (cloth / leather / chain, with the chain metal
  textures found next to the model), saddle, saddle bags, Christmas sack, bridle, horseshoes (with
  shoe metals). The plain horse is shown by default. The game picks these meshes itself, so which
  barded body (`BodyBarded01-03`) goes with which barding isn't in the files: "auto" pairs them by
  number (cloth 01, leather 02, chain 03); switch **Body under barding** if the game looks different.
  Coat colours come from the mappings.txt items (Item / variant menu).
- **Normal maps**: like the game, a texture's normal map is found by name (`Dog.dds` →
  `Dog_n.dds`) and used for surface detail. Switch it off, or flip its green channel, in the Model panel.
- **Helmets**: the model is the mappings.txt entry with the same key as the armor.xml item (armor.xml
  only has its flags). The worn model is tried first: `<key>.equipped.<gender>`, then `<key>.equipped`
  (e.g. `chain_coif_head.wom`), then `<key>` itself (that one is often the item lying on the ground);
  `….iron`-style keys fall back to the base key. It is attached to the
  NullHelmet bone and placed with the `<offsetToNull>` values from the helmet folder's
  properties.xml. `removeHead` / `showHair` are applied only when the helmet model is found.
- **Jewellery**: **Neck** (necklaces, medallions) and **Belt** are their own outfit slots (textures,
  drawn over the armour). **Left / Right ring** (`model.decoration.ring…`, on the middle finger)
  and **Left / Right bracelet** (`model.decoration.armring…`, on the wrist) are models placed with
  the offsets in `player/accessories/properties.xml`. The game has no earrings; earring slots appear
  when a custom object has `earring` in its name. Any properties.xml `<offsetToNull>` is used, for any Null bone.
- **Animations**: everything properties.xml lists for the model, with play/pause, speed, loop and a
  time slider.
- **Save body texture / Save face texture** saves the composed textures as PNG.
- **Dye (paint mask)**: ships, boats, wagons and carts get a Dye panel. The mask comes from
  properties.xml: `<mask>caravel_pm.dds</mask>` (whole model) or
  `<meshMask><mesh>wagon</mesh><mask>cart_m.dds</mask></meshMask>` (one mesh). In the mask,
  yellow = main / wood dye, blue = cloth (sail) dye, black = never dyed. Set each dye as 0-255 RGB
  (or the colour picker), with a strength slider and three blends: true colour (the default: the
  dye's own colour, so white stays white, with the texture's light and shade kept), colour layer
  (a see-through colour over the texture) or multiply. The normal map stays on.
  Dye doesn't work as it does in the game yet. Once we understand how the game works with dye we
  will make a better version. For the moment, use it to confirm that your model's `<name>_m.dds`
  dye area texture file is correct.
- **Lighting (photo studio)**: starts with one white light. Add up to 8 lights. Each light has:
  - on/off, a type (bulb, spotlight or sun) and its own shadow switch
  - a colour as 0-255 RGB (to match dyed lamps from the game) or as hue / saturation / luminance
  - brightness and range, plus inner and outer angles for spotlights
  - a position around the model: Around (0 = in front), Height and Distance (in model sizes)

  The Scene part sets the ambient light and colour, the background, the floor (grid, solid, shadow
  catcher or none), tone mapping and exposure. Ready-made setups: three-point, torch-lit night,
  moonlight, neon rims and daylight. Move the open light with the keys (A/D around, W/S nearer or
  further, R/F up or down, Shift for big steps), or use "Place at camera". Spotlights and suns can
  be aimed: Turn (left/right) and Tilt (up/down) point them away from the model's centre (arrow keys
  do the same), and "Aim at model" points them back. A line shows where each one points. Light
  markers and aim lines are hidden in screenshots.
- **Armour dye**: in the Outfit panel each worn piece (not helmets) gets a "dye" box and colour. The
  piece takes on the dye's own colour (white stays white, black scale armour can be dyed light) and
  keeps its texture's light and shade, with a shared strength slider.
  Dye doesn't work as it does in the game yet. Once we understand how the game works with dye we
  will make a better version. For the moment, use it to confirm that your model's `<name>_m.dds`
  dye area texture file is correct.
- **Metal look**: every object (not characters) gets a Metal panel: show it in iron, steel, gold,
  silver, copper, bronze, brass, lead, zinc, tin, adamantine, glimmersteel, seryll, moon metal or
  electrum. It changes the colour (texture detail kept; strongly coloured parts such as a red plume
  are left alone), the highlight colour and how sharp the shine is. Parts: the ones that look like
  metal by mesh or texture name, or the whole model.
- **Mount gear colours**: barding, saddle, bridle and saddle bags each get a colour box, with the
  texture detail kept.
- **Highlights** (Model panel): "realistic" gives a sharp, bright shine on shiny metal and a broad,
  soft one on cloth and skin, from each material's shininess, with a brighter rim at low angles;
  "classic" is the plain Phong shine from before.
- **Clean see-through edges** (Model panel, on by default): hair, leaf and lace textures often
  hide black colour in their clear pixels, which shows as a dark rim around the edges. The viewer
  fills those clear pixels with the colour of the nearest visible ones when it loads the texture
  (only in the viewer; your files are not changed).

What it can't know: the exact blend the game uses for dyes (compare the two blends and the strength
with the game), the exact blend the game uses for each face layer (it layers by transparency,
and multiplies layers that have none), and skin tint. Use it as a close preview, not a pixel-exact
copy of the game.

## Converting a whole folder

```
python wom_tool.py batch  "D:\WurmUnlimited\player"            # -> D:\WurmUnlimited\player_obj
python wom_tool.py batch  "D:\WurmUnlimited\player" --png      # textures converted to .png (needs: pip install pillow)
python wom_tool.py batch-back "D:\WurmUnlimited\player_obj"    # every edited .obj -> .wom, in D:\WurmUnlimited\player_obj_wom
```

`batch` goes through the folder and all subfolders and writes a mirror copy to a new folder, so
the game folder isn't touched. For every model .wom it writes:
- the `.obj`, `.mtl` and `.womdata.json`;
- every other file in the folder (all textures in every resolution folder, armor.xml, properties.xml,
  ...) copied into the output folder with the same layout (converted to .png with `--png`,
  upscaled with `--upscale`). Each .mtl points at the texture its model uses inside that copy. A .wom often names a texture differently from the file on disk, e.g. it asks for
  `Female_default_nude.png` while the game has `textures/2048/Base/Female_default_nude.dds`.
  The tool matches by name, ignores the extension, and takes the highest resolution
  (2048 > 1024 > 512 > 256);
- for each character listed in a `properties.xml`, a `<model>_anims.glb` with the model,
  skeleton and every animation file its `<anim>` section points to.

Animation .wom files are recognised automatically (they go into the .glb files, not OBJ).
`conversion_report.txt` in the output folder lists every file and any missing textures,
missing animations or failures. A broken file is reported and skipped; the rest still convert.

`batch-back` rebuilds every .obj that has a `.womdata.json` next to it. Files you didn't edit
come back byte-identical.

## mappings.txt (which game item uses which file)

Put the game's `mappings.txt` next to `wom_tool.py`. `batch` then uses it automatically
(`--no-mappings` to skip), or run it on its own:

```
python wom_tool.py mappings "D:\WurmUnlimited\player"          # output goes to D:\WurmUnlimited\player_obj
```

Output, all in the `_obj` folder:
- `mappings_matched.txt`: every line whose file exists in your folder, with its `###` section
  headings. The folder can be a sub-folder of the game (e.g. just `player`). The tool works out
  which path prefix to drop (`player/`), and file names are matched ignoring letter case.
- `mappings_missing.txt`: lines that point into your folder at files that aren't there.
- `_mappings.txt` in each sub-folder: the lines for the files in that folder.
- **Variants.** Many items share one .wom and only swap textures or material values with
  `?Material.texture=...&Material.specular=r,g,b,a&Material.shininess=n&Material.emissive=...`.
  Each such line becomes `<model>__<item>.obj/.mtl`, e.g. `tallStoneWallPortcullis__marble.obj`,
  with that item's textures (looked up by name across the folder, copied alongside) and its
  specular/shininess/emissive values in the .mtl. Open one in Blender to see that item.
  Variants are previews: `batch-back` skips them, because the game builds them from the shared
  .wom plus the mappings line.

## Hair: it's in separate files

Hair isn't in the body model. It's in `player/hair/femaleHair01.wom` to `femaleHair07.wom`
(male: `male_hair01` to `05`), each with its own texture (`Female_hair_01.dds` ...).
The hairstyle slots are set in `mappings.txt`:

```
hair0.female = player/hair/femaleHair01.wom      ... up to
hair6.female = player/hair/femaleHair07.wom      // hair7 is buzz, no model
hair1 = player/hair/male_hair01.wom ... hair5     // male; hair 0 is buzz
```

So a new hairstyle can go in by pointing a slot at your file, e.g.
`hair6.female = player/hair/femaleHair08.wom`, or by editing one of the existing hair files in place.
Server and client side mods are needed to add slot numbers beyond the existing ones (`hair8.female`),
so the best is to replace an existing one and have players that don't have the new models fall back
on the old one. Using the replace method for a new model, the client will show the new one and
report it as slot 7 to the server if it is named `femaleHair07.wom`, and players without the new
model will see the old `femaleHair07.wom`, not a missing texture and model.

`armor.xml` only switches pieces on/off under helmets (`<showHair/>`,
`<removeHead/>`, `<removeMask/>`).

## Hair and helmets in Blender

Hair and helmet .wom files have no skeleton: they're modelled around the head's NullHelmet bone,
so on their own they sit at the ground in Blender. To edit them in place on the body:

```
python wom_tool.py wom2obj femaleHair01.wom --attach-to female_1_04.wom
python wom_tool.py wom2obj greatHelmet01.wom --attach-to Male_1_04.wom     # uses offsetToNull too
```

The .obj then sits on the body's head (helmets also get their `<offsetToNull>` from the
properties.xml next to them). Import the body's .obj as well to model against it. `obj2wom` reads the
placement from the `.womdata.json` and moves the result back to the game's origin automatically.

`batch` does this by itself for every bone-less model in a `hair` or `helms` folder, using
`female_1_04.wom` for files with "female" in the name and `Male_1_04.wom` for the rest
(`--no-place` turns it off). The report says which body each file was placed on.

## Editing a model (e.g. adding a part to female_1_04)

1. `python wom_tool.py wom2obj female_1_04.wom`
2. In Blender: File → Import → Wavefront (.obj). Every WOM mesh comes in as its own object
   (131 of them, many stacked on top of each other: the face/torso/leg variants). Hide what you
   don't need, but **don't delete or rename** existing objects unless you mean to remove them.
3. Model your new part as a new object and give it a new name ending in `Mesh`, for example
   `hair05Mesh` (any new name works). Pick how it moves with the skeleton:
   - `hair05Mesh@Head`: the whole mesh is locked to the Head bone (best for short hair).
   - `hair05Mesh`: each vertex takes blended weights from the closest point on the body (good for long hair
     that should follow the neck/spine). To limit which body parts it copies from, use
     `--weights-from backpartMesh,upperFace0Mesh,torso00Mesh`.
   The `@Head` suffix is removed from the final mesh name.
4. Material: assign an existing material (`female_Nude_Mat`) to reuse its texture, or a new
   material whose image texture is your texture file. Its file name goes into the WOM, so use
   the name the game has (usually `.dds`) even if Blender shows a .png copy.
5. File → Export → Wavefront (.obj) with **UV coordinates, Normals, Materials, Triangulated
   Mesh** on, Forward −Z / Up Y (the defaults), and save over `female_1_04.obj`.
6. `python wom_tool.py obj2wom female_1_04.obj -o female_1_04.wom`

The tool prints what it did with each mesh (unchanged / edited / new + how it was weighted).

## What carries through

- Untouched meshes are written back byte-for-byte as they were.
- Edited existing meshes keep their bone weights: each vertex gets the weights of the closest point
  on the original surface, blended across that triangle. Subdivided meshes therefore bend smoothly.
- Joints, attachment points (Null… joints such as NullHelmet), and mesh order are preserved.
  New meshes are inserted before `pickingBoxMesh` and `boundingBoxMesh`.
- Animations live in separate files in Wurm Unlimited, not in the .wom. They work as long as the skeleton is
  unchanged, which this tool guarantees (bones can't be added or moved).

## Animations (the files in /Anim)

The animation .wom files use a different format from the models. Each one is a list of bones,
each with keyframes (a bone transform relative to its parent plus a time, 30 per second).
They're matched to the skeleton by bone name. OBJ can't hold animation, so animations go
through glTF (.glb), which Blender imports and exports natively.

```
# model + any number of animations -> one .glb (each animation becomes a Blender action)
python wom_tool.py glb female_1_04.wom bow.wom kneel.wom meditate.wom -o female.glb

# optional: only include some meshes so the 131 stacked variants don't clutter the view
python wom_tool.py glb female_1_04.wom kneel.wom --meshes "^(backpart|upperFace0|lowerFace0|nose0|torso00|tasset00|UA00|LA00|hand00|legs00|LL00|foot00)"

# animations in a .glb -> one animation .wom per action/animation, named after it
python wom_tool.py glb2anim female_edited.glb female_1_04.wom -o Anim_out
python wom_tool.py glb2anim female_edited.glb female_1_04.wom --only wave --template bow.wom
```

**Making a new animation in Blender**
1. File → Import → glTF 2.0, and pick the .glb. Put the texture .png files in the same folder
   if you want to see textures.
2. Select the armature and, in the Action Editor (Dope Sheet), create a new action named after
   your animation, e.g. `wave`. Pose bones and insert keyframes. Don't add, delete or rename
   bones; the game's skeleton is fixed.
3. File → Export → glTF 2.0 (.glb) with Animation enabled. Export all actions, or just yours.
4. `python wom_tool.py glb2anim yourfile.glb female_1_04.wom --only wave -o out`
   Output is resampled to 30 keys/second like the game files (`--fps 0` keeps your keys).
   `--template bow.wom` copies an existing file's bone list and order exactly.

It doesn't matter if Blender changes the bone orientations on import ("Bone Dir" setting) or if
the armature is rotated or scaled. The tool measures that against the real skeleton and cancels
it out.

The animation files work on both female and male, so one made on the female skeleton
should play on the male too, provided he has the same bone names.

Which file the game plays for an action is decided by the client, so a brand-new animation file
needs something in the game (or a client mod) that asks for it. The easiest way to test is to
replace an existing animation file, e.g. a copy of `bow.wom`.

## Upscaling textures (AI)

```
python wom_tool.py setup-gpu                          # once: downloads the GPU engine (~45 MB), tests it, lists your GPUs
python wom_tool.py gpu-check                          # test the engine again and list the GPUs it can use
python wom_tool.py upscale "D:\WurmUnlimited\player" --gpu-id 0,1   # share the work between two GPUs
python wom_tool.py upscale "D:\WurmUnlimited\player\textures"  # -> D:\WurmUnlimited\player\textures_upscaled
python wom_tool.py upscale bodybag.dds --scale 4      # one file -> bodybag_x4.dds
python wom_tool.py batch "D:\WurmUnlimited\player" --upscale 2  # convert models AND upscale the textures they use
```

- **Speed.** The GPU engine runs once per batch of textures and processes several images at the
  same time: as many as your free video memory allows, about 1.4 GB each. Video memory is read from
  `nvidia-smi` on NVIDIA cards; on AMD Radeon and Intel Arc it comes from what Windows records for
  the card (or the amdgpu driver on Linux), keeping ~1.5 GB spare.
  Reading and finishing the textures (resizing, colour, transparency, DDS compression with mipmaps)
  runs on several CPU cores at once, while the GPU works on the next batch.
  - `--gpu-jobs N`: images on the GPU at once (if it runs out of video memory it retries with 1)
  - `--cpu-jobs N`: CPU workers (default: all threads − 1, up to 16)
  - **P-cores and E-cores** (Intel 12th gen and newer, Apple Silicon): the tool detects them and
    shows the split, e.g. "16 P-core threads + 8 E-cores". By default it uses both, which gets the
    most work done; Windows puts each worker on a core. `--cpu-cores p` keeps the workers on the
    P-cores only (fewer workers, each faster; handy if you keep using the PC meanwhile). Keeping
    workers on the P-cores works on Windows and Linux; on a Mac it only changes the count.
  - `--tile N`: smaller GPU tiles use less video memory
  - Textures already done are **skipped**, so a stopped run carries on where it left off
    (`--redo` to do them all again).
  - Every GPU result is checked against the original. If the GPU was reset mid-image (screensaver,
    driver hiccup), leaving it partly black, it is redone automatically: first on the GPU one at a
    time, then on the CPU.
  - `--repair` checks an already finished folder and redoes **only** the damaged textures, e.g. after
    a crash. Much faster than `--redo`.
  - Turn off the screensaver and display sleep for long runs; they can reset the GPU.
  - The time-left estimate weighs AI textures by their size, so it no longer jumps up once the quick
    copies are done.
  - For 2x, `--model realesr-animevideov3-x2` is much faster than the default x4plus (which has to make
    a 4x picture and shrink it). It is tuned for drawn art, so compare on a few textures first.
  - If the GPU engine can't run on your PC, the tool says so once and does the rest on the CPU.
- **Engine.** With `setup-gpu` done, it uses `realesrgan-ncnn-vulkan` (Real-ESRGAN x4plus) on your GPU. It
  runs through Vulkan, so it works on **NVIDIA, AMD Radeon and Intel Arc** cards (and built-in
  graphics), with no CUDA needed. Keep the graphics driver up to date; if the test in `setup-gpu` /
  `gpu-check` fails, a driver update usually fixes it. On a PC with two GPUs (e.g. Intel built-in
  graphics plus a Radeon or Arc card), `gpu-check` lists them with numbers: add `--gpu-id N` to
  `upscale` or `batch` to pick the strong one. Without it, or if the GPU run fails, it uses
  the built-in CPU model (Real-ESRGAN "general, weak denoise"), which is slower: about 15 s for a 512
  texture, about 1 min for a 1024. `--engine gpu|cpu|lanczos` forces one.
- **Several GPUs** (e.g. two RTX 5090s): `--gpu-id 0,1` or `--gpu-id all` shares the pictures between
  them. Each GPU gets its own images-at-once count from its own free video memory (or `--gpu-jobs N`
  for each). With very fast GPUs the CPU finishing work (DDS compression, mipmaps) can become the
  slow part: raise `--cpu-jobs` if the CPU isn't busy. `--gpu-id all` takes every GPU the engine
  lists, built-in graphics included, so with a strong pair plus built-in graphics name the two.
- **Laptops with built-in + dedicated GPU:** the built-in GPU (Intel UHD/Iris/Arc Graphics, AMD
  Radeon 680M/780M/890M…) can only help with the AI upscaling, not with the CPU work (reading,
  colour, DDS compression and mipmaps run in Pillow/numpy, which use the CPU only). With
  `--gpu-id all` (or `0,1`) it is recognised and given 1 image at a time, so the slow chip never
  holds up the end of a run; `--gpu-jobs 4,1` sets a count per GPU yourself. On a laptop the
  built-in GPU shares the processor's power and cooling, so it can slow the CPU work down: compare
  a run with only the dedicated GPU (the default) before keeping it.
- **DDS in, DDS out:** same compression (DXT1/DXT3/DXT5), and a full mipmap chain if the original
  had one, so the game can load the files directly. Odd sizes like 1020x699 are fine.
- **Resolution tiers.** The game keeps most textures in `textures/256`, `512`, `1024` and `2048`. When the
  folder has these, each lower tier gets the **real artwork from the tier above** (e.g. the 512 file
  becomes the real 1024 art). Only the top tier (2048 -> 4096) is AI-upscaled. That gives far better
  results than upscaling a 256 file: the 256 versions are too compressed for any AI to recover the
  2048 detail. `--no-tiers` turns this off.
- **Colour.** By default the AI only changes brightness detail, and colour comes from a normal resize.
  This avoids the coloured fringes the AI otherwise adds around edges (`--full-color` lets the AI
  change colour too).
- **Fabric and fine patterns.** AI upscalers smooth fine noise such as cloth weave. If it looks too
  clean, use `--strength 0.7`, which blends 70% AI with 30% plain resize.
- **Not AI-upscaled by default:** normal maps (names like `_n`, `_normal`) and alpha/transparency,
  which get a plain resize so edges and lighting stay correct (`--ai-normals`, `--ai-alpha` override).
- **Size cap:** `--max-size 4096` by default. Bigger textures cost game memory; 4096 is already 4x
  the 2048 tier.

Real-ESRGAN (c) Xintao Wang, BSD-3-Clause licence; see REALESRGAN_LICENSE.txt.
The viewer uses three.js (MIT licence); see THREEJS_LICENSE.txt (next to wom_viewer.html in the release, in the WOM-Viewer folder of the source).

## Limits

- Max 65,535 vertices per mesh (WOM uses 16-bit indices).
- Max 4 bone influences per vertex (as in the game files).
- Polygons are triangulated (fan); vertex colours aren't supported (none of the game files use them).
