# User Packs

Client mod for Wurm Unlimited (Ago's client mod loader). The beta branch of Wurm Unlimited loads
every `.jar` in `WurmLauncher\userpacks` as a resource pack; the normal branch doesn't. This mod
adds the same loading to the normal client:

- Every `.jar` in `WurmLauncher\userpacks` loads at game start, in front of the game's own packs.
- When two packs change the same thing, the one whose name comes last in the alphabet wins (the same as the beta).
- On the beta client, which loads userpacks itself, the mod does nothing, so it can stay installed.

Useful for the [WU-Upscaler](../WU-Upscaler) packs, texture packs and model replacements when you
don't want the beta branch. See [UserPacksREADME.txt](UserPacksREADME.txt).

**Download:** the `UserPacks` zip on the [Releases](https://github.com/axeblade346/WurmUnlimitedMods/releases) page.
