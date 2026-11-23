# Code Names

Client mod for Wurm Unlimited (Ago's client mod loader). Adds the game's code name of whatever is
under the mouse to the hover tooltip. Works with the normal tooltip and with SkloGraphics' hover card.

| Hovering | Shows |
|---|---|
| cave walls | `img.texture.cave.marble`, ore textures |
| ground tiles | `img.texture.terrain.grass`, plus the tree or bush model |
| items | the model name the server sent, e.g. `model.rune.magranon.rift crystal.cherrywood.` |
| creatures, walls, fences, floors, roofs, bridges | their model names |

With `showFiles=true` it also shows the file that was used and the pack it came from, for example
`UP_creatures_Horses.jar:creatures/horse/Horse_main.wom`.

That's what you need to replace one item's model with a userpack: map the full name the server
sends to your own `.wom`. See [CodeNamesREADME.txt](CodeNamesREADME.txt).

Console (F1): `codenames on|off`, `codenames files on|off`, `codenames all on|off` (`cn` for short).

It only shows names the client already has; nothing is sent to the server.

**Download:** the `CodeNames` zip on the [Releases](https://github.com/axeblade346/WurmUnlimitedMods/releases) page.
