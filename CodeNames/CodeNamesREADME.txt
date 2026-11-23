Code Names 1.3 - client mod for Wurm Unlimited (Ago's client mod loader)
=========================================================================

Shows the game's code name of whatever is under the mouse in the hover tooltip
(the normal one and SkloGraphics' hover card):

  cave walls     img.texture.cave.marble, img.texture.cave.ore.iron, ...
  ground tiles   img.texture.terrain.grass, ... and the tree/bush model on tree tiles
  items          the model name the server sent, e.g. model.decoration.statue.custom
  creatures      model.creature....
  walls, fences, floors, roofs, bridges: their model names

With showFiles=true it also shows the file that was used, with the pack it came from
(e.g. graphics.jar or one of your userpacks) - so you can see what an item fell back to.

It only shows names the client already has. Nothing is sent to the server.

Install: copy the mods folder into WurmLauncher (mods\codenames.properties and
mods\codenames\codenames.jar).

Console (F1):  codenames on | codenames off | codenames files on | codenames files off
               codenames all on | codenames all off  (every hidden line, unfiltered)
               (cn works as a short form)

Replacing a server's custom item with your own model
-----------------------------------------------------
A server can give a custom item its own model name, such as model.decoration.statue.custom,
while having no model of that name. The client then drops the last part and tries again
(model.decoration.statue), so the custom item borrows an existing model.

1. Hover the item in the world (placed or on the ground). The tooltip shows the full name the
   server sent, and the file it ended up using.
2. Make a userpack .jar with your model and a mappings.txt line for that FULL name:
       model.decoration.statue.custom = mymodels/statue_custom.wom
   plus your .wom, its textures and (if it has masks or settings) a properties.xml next to it.
   Textures are looked up in the same pack as the .wom, so put them in the same .jar.
3. Put the .jar in WurmLauncher\userpacks. Only that item changes; the normal statue
   keeps its own model.

Bugs: contact Axeblade - axeblade346 on the Sklotopolis forums, axeblade on the Wurm modding discord.

Source code: https://github.com/axeblade346/WurmUnlimitedMods (CodeNames folder)
