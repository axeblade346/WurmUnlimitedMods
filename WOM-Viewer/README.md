# WOM Viewer for Wurm Unlimited.

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

This is the viewer on its own. The full WOM-Converter package also has the .wom <-> .obj converter,
batch conversion, animations and texture upscaling.

Needs a browser (Chrome, Edge or Firefox). The launcher (WOM Viewer.bat / wom_viewer.py) needs
Python 3.8+ only, no extra packages: https://www.python.org/downloads/ (tick "Add python.exe to
PATH" if the installer shows it). Without Python, open wom_viewer.html directly and pick graphics.jar.

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
