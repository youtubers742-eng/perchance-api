# -*- coding: utf-8 -*-
"""Perchance art-style templates.

Transcribed from the style list shipped with akashayguta/perchance-image-api
(styles.json, 75 styles). Each template is a prompt suffix/prefix with a
``{prompt}`` placeholder. ``{a|b}`` groups resolve to the first option and
``[input...]`` fragments are stripped by :func:`apply_style` (same behaviour
as the reference wrapper).
"""

import re

STYLES = {
    "Casual Photo": "A casual real-life photograph. A casual photo of {prompt}. It's a casual photo. Overall it's an actual real-life photograph.",
    "Cinematic": "{prompt}, cinematic shot, dynamic lighting, 75mm, Technicolor, Panavision, cinemascope, sharp focus, fine details, 8k, HDR, realism, realistic, key visual, film still, cinematic color grading, depth of field.",
    "Digital Painting": "{prompt}, breathtaking digital art, trending on artstation, in the style of atey ghailan, in the style of greg rutkowski, in the style of greg tocchini, in the style of james gilleard, 8k, high resolution, best quality.",
    "Concept Art": "{prompt}, concept art, digital art, illustration, inspired by wlop style, 8k, fine details, sharp, very detailed, high resolution, world-class masterpiece.",
    "3D Disney Character": "3D cartoon Disney character portrait render. {prompt}, bokeh, 4k, highly detailed, Pixar render, CGI Animation, Disney, cute big circular reflective eyes, dof, cinematic film, Disney realism, subtle details, breathtaking Pixar short, fine details, close up, sharp focus, HDR, Disney-style octane render, incredible composition, superb lighting and detail, {prompt}.",
    "2D Disney Character": "2D cartoon Disney character digital art of {prompt}. superb linework, classic 2D Disney style art, inspired in the style of the art styles of Glen Keane and Aaron Blaise, Disney-style character concept with a Disney-style face, trending on artstation, Disney-style version of {prompt}.",
    "Disney Sketch": "Glen Keane character concept art black and white pencil sketch of {prompt}. rough pencil sketch in the style of Glen Keane, rough pencil sketch, close up, loose Disney-style character concept art sketch, nice sketchy pencil strokes, Disney character design sketch, pencil texture, a concept art pencil sketch of {prompt}, in the style of Glen Keane.",
    "Concept Sketch": "black and white technical drawing showcasing {a} {prompt}, annotation details, world-class masterpiece black and white, pencil strokes, annotated technical concept art sketch, pencil texture.",
    "Painterly": "painterly digital painting, {prompt}, digital painting in the style of Ilya Kuvshinov with painterly brush strokes, in the style of Ilya Kuvshinov, world-class painterly masterpiece.",
    "Oil Painting": "breathtaking alla prima oil painting, {prompt}, close up, alla prima style, oil on linen, painterly oil on canvas, painterly style, exquisite composition and lighting, modern painterly masterpiece, in the style of alexi zaitsev, award-winning painterly alla prima oil painting.",
    "Oil Painting - Realism": "breathtaking oil painting, {prompt}, photorealistic oil painting, in the style of charlie bowater, fine details, in the style of wlop, trending on artstation, very detailed.",
    "Oil Painting - Old": "{prompt}, Oil painting in the style of Jean-François Millet and Gustave Courbet and Jules Breton",
    "Oil Painting - 70s Pulp": "1970s vintage pulp art, ultra realistic, fully restored, exquisite lighting and composition, polished, masterpiece, vintage pulp art, in the style of Earle K. Bergey, in the style of Kelly Freas, in the style of Alex Schomburg, in the style of H. J. Ward, glossy pulp art, Amazing Stories, Weird Tales, 8k, high resolution, best quality, hyper-realistic, Mattias Adolfsson style, detailed stylization, {prompt}, ultra realistic, wlop-style, exquisite lighting and composition, polished, world-class masterpiece, digitally enhanced, breathtaking shot, subtle details, superb quality, art in the style of Kuvshinov, Kuvshinov style, detailed stylization.",
    "Professional Photo": "{prompt}, {sharp|soft} focus, depth of field, 8k photo, HDR, professional lighting, taken with Canon EOS R5, DSLR, 75mm lens",
    "Anime": "anime art of {prompt}, world-class masterpiece, 4k, best quality, anime art.",
    "Drawn Anime": "anime-style illustration with perfect clean lines, illustration of {prompt}, anime drawing/art, bold linework, illustration, cel shaded, anime-style digital illustration. It's an anime-inspired 2D-style anime illustration. Aesthetic high-skill, professional anime illustration, which looks like a screencap from an anime series. It has clean line work and a pleasant, appealing drawn aesthetic style. Overall, it's a world-class illustration with flawless line work, perfect composition, and impeccable attention to detail.",
    "Anime Screencap": "Anime screencap, {prompt}. It's an anime screencap from a popular anime. Beautiful visual quality, remastered, extremely high quality, very aesthetic, high production value, high-skill masterpiece. The image shows impeccable and beautiful composition and contrast. It's an exquisite anime screencap style image.",
    "Cute Anime": "adorable, cute, kawaii, {prompt}, cute moe anime character portrait, adorable, featured on pixiv, kawaii moé masterpiece, cuteness overload, very detailed, sooooo adorable.",
    "Soft Anime": "{prompt}, anime masterpiece with soft lighting, gentle intricate style, highly detailed, pixiv, anime art, 4k, art from your name anime, garden of words style art, high quality.",
    "Fantasy Painting": "{prompt}, d&d, fantasy, highly detailed, digital painting, artstation, sharp focus, fantasy art, illustration, 8k, in the style of greg rutkowski. It's an absolute world-class masterpiece artwork. It's an aesthetically pleasing artwork with impeccable attention to detail and impressive composition.",
    "Fantasy Landscape": "{prompt}, fantasy matte painting, absolute masterpiece, detailed matte painting in the style of andreas rocha and greg rutkowski, in the style of Brothers Hildebrandt, superb composition, vivid fantasy art, breathtaking fantasy masterpiece. It's an absolute world-class masterpiece artwork. It's an aesthetically pleasing artwork with impeccable attention to detail and impressive composition.",
    "Fantasy Portrait": "{prompt}, d&d, fantasy, highly detailed, digital painting, artstation, sharp focus, fantasy art, character art, illustration, 8k, art in the style of artgerm and greg rutkowski. It's an absolute world-class masterpiece artwork. It's an aesthetically pleasing artwork with impeccable attention to detail and impressive composition.",
    "Studio Ghibli": "Studio Ghibli style artwork of {prompt}, Studio Ghibli style art film still, sharp, very detailed, high resolution, inspired by the style of Hayao Miyazaki, anime, film still from Spirited Away. In the style of Kiki Delivery Service, with a similar art style to Princess Mononoke. Aesthetically similar to My Neighbor Totoro's art style.",
    "50s Enamel Sign": "50s enamel sign of {prompt}, 50s advert enamel sign, masterpiece, authentic vintage enamel sign",
    "Vintage Comic": "comic book style art of {prompt}, drawing, in the style of Dave Stevens, in the style of Adam Hughes, 1940's, 1950's, hand-drawn, color, high resolution, best quality, closeup",
    "Franco-Belgian Comic": "franco-belgian color comic about {prompt}, bande dessinée, franco-belgian comic panel, masterpiece, breathtaking composition, intricate, detailed, best quality",
    "Tintin Comic": "color comic panel in the style of Hergé about {prompt}, in the style of Hergé, tintin style, french comic panel, franco-belgian style, masterpiece, high-resolution Hergé style",
    "Medieval": "medieval illuminated manuscript picture of {prompt}, medieval illuminated manuscript art, masterpiece medieval color illustration, 16th century, 8k high-resolution scan of 16th century illuminated manuscript painting, detailed medieval masterpiece.",
    "Pixel Art": "{prompt}{prompt}, best pixel art, neo-geo graphical style, retro nostalgic masterpiece, 128px, 16-bit pixel art {prompt}, 2D pixel art style, adventure game pixel art, inspired by the art style of hyper light drifter, masterful dithering, superb composition, beautiful palette, exquisite pixel detail",
    "Furry - Oil": "{prompt}, crisp vibrant detailed soft painterly digital art, volumetric lighting, natural lighting, realistic lighting, vibrant colors, crisp oil painting, painterly realism, depth of field, subtle soft details, vivid, fresh, striking, in the style of chunie, in the style of darkgem, in the style of honovy, inspired by zaush, inspired by anhes, inspired by puinkey, in the style of caraid, in the style of dagasi, inspired by taranfiddler, in the style of atey ghailan, in the style of MilletGustave, in the style of Curbet, inspired by Charlie Bowater style, lol art.",
    "Furry - Cinematic": "{prompt}, cinematic shot, dynamic lighting, 75mm, Technicolor, Panavision, cinemascope, sharp focus, fine details, 8k, HDR, realism, realistic, key visual, film still, cinematic color grading, depth of field.",
    "Furry - Painted": "anthro {prompt} digital art, masterpiece, 4k, fine details. It's an absolute world-class masterpiece artwork.",
    "Furry - Drawn": "anthro {prompt} illustration, hand-drawn, bold linework, anthro illustration, cel shaded, 4k, fine details, masterpiece.",
    "Cute Figurine": "{prompt}, figurine, modern Disney style, octane render, chibi",
    "3D Emoji": "masterpiece {prompt} cartoon 3D emoji concept render, close-up, facing forward, matte finish, 3D emoji render, app icon, simple design, new iOS 18.4 style {prompt} emoji render, simple background, centered, world-class masterpiece work of art, crisp render, sharp focus, charmingly aesthetic design, 4k, soft lighting, masterpiece emoji-style figurine 3D render, pure white background",
    "Illustration": "breathtaking illustration of {prompt}, illustration, masterpiece, breathtaking illustration.",
    "Flat Illustration": "{prompt}, illustration, flat, 2D, vector art, masterpiece, made with adobe illustrator, behance competition winner, trending on dribble, 4k, high resolution, crisp lines.",
    "Watercolor": "{prompt}, (watercolor), high resolution, intricate details, 4k, wallpaper, concept art, watercolor on textured paper.",
    "1990s Photo": "{prompt}, 90s home video, nostalgic 90s photo, taken with kodak disposable camera",
    "1980s Photo": "famous vintage 80s photo, {prompt}, grainy photograph, 80s photo with film grain, Kodacolor II 80s photo with vignetting, retro, r/OldSchoolCool, 80s photo with wear and tear and minor creasing and scratches, vintage color photo",
    "1970s Photo": "famous vintage 70s photo, {prompt}, grainy photograph, 1970s photo with film grain, 70s photo with vignetting, retro, r/OldSchoolCool, 70s photo, vintage photo",
    "1960s Photo": "famous vintage 60s photo, {prompt}, grainy photograph, 1960s photo with film grain, 60s photo with vignetting, retro, r/OldSchoolCool, 60s photo, vintage photo",
    "1950s Photo": "famous vintage 50s photo, {prompt}, grainy photograph, 1950s photo with film grain, 1950s photo with vignetting, retro, r/OldSchoolCool, 1950s photo, vintage photo",
    "1940s Photo": "famous vintage 1940s photo, {prompt}, grainy photograph, 1940s photo with film grain, 1940s photo with vignetting, retro, r/OldSchoolCool, 1940s photo, vintage photo",
    "1930s Photo": "famous vintage 1930s photo, {prompt}, grainy photograph, 1930s photo with film grain, 1930s photo with vignetting, retro, r/OldSchoolCool, 1930s photo, vintage photo",
    "1920s Photo": "{prompt}, 1920s photo, restored photograph, {sepia|black and white}, historical archive photo",
    "Vintage Pulp Art": "1970s vintage pulp art, {prompt}, vintage pulp art, in the style of Earle K. Bergey, in the style of Kelly Freas, in the style of Alex Schomburg, in the style of H. J. Ward, glossy pulp art, Amazing Stories, Weird Tales, 8k, high resolution, best quality",
    "50s Infomercial Anime": "{prompt}, 1950s infomercial style, delicate linework, paprika anime art style, chromatic aberration glow, 2d painted cel animation, soft focus, 2D pixiv 1950s",
    "3D Pokemon": 'An incredibly perfect high-quality 3D render of a pokemon creature, {prompt}, [input.pokemonType ? input.pokemonType+", " : ""]8k render, beautiful pokemon digital art, fakemon, pokemon creature, cryptid, fakemon, masterpiece, soft focus, best quality, high quality. Perfect soft lighting, beautiful composition. It\'s an impressive CGI image from the upcoming Pokemon Movie (2026).',
    "Painted Pokemon": 'Beautiful, very high-quality painterly digital concept art, {prompt}, [input.pokemonType ? input.pokemonType+", " : ""]8k digital painting of a pokemon, amazing pokemon creature art in the style of piperdraws, cryptid creations in the style of Piper Thibodeau, in the style of Naoki Saito and {Tokiya|Mitsuhiro Arita}, incredible composition.',
    "2D Pokemon": 'Beautiful, very high-quality painterly digital concept art, {prompt}, [input.pokemonType ? input.pokemonType+", " : ""]pokemon creature concept, superb line art, beautiful colors and composition, 2D art style, beautiful pokemon digital art, fakemon, in the style of Sowsow, pokemon creature, cryptid, fakemon, masterpiece, in the style of Yuu Nishida, 4k. The Pokémon-like creature is centered within this anime-style 2D image. It\'s from the upcoming Pokemon Movie (2026) which has the classic 2D Pokemon art style.',
    "Vintage Anime": "{prompt}, 1990s anime, vintage anime, 90's anime style, in the style of hajime sorayama, in the style of greg tocchini, anime masterpiece, pixiv, akira-style art, akira anime art, 4k, high quality.",
    "Neon Vintage Anime": "{prompt}, neon vintage anime style, 90's anime style, 1990s anime, hajime sorayama, greg tocchini, neon vintage anime masterpiece, anime art, 4k, high quality.",
    "Manga": "{prompt}, incredible hand-drawn manga, black and white, in the style of Takehiko Inoue, in the style of Katsuhiro Otomo and akira toriyama manga, hand-drawn art in the style of rumiko takahashi and Inio Asano, Ken Akamatsu manga art.",
    "Fantasy World Map": "beautiful fantasy map of {prompt}, beautiful fantasy map inspired by middle earth and azeroth and discworld and westeros and essos and the witcher world and tamriel and faerûn and thedas, 4k, beautiful colors, crisp, high-resolution artistic map, topographic 3D terrain, artistic map.",
    "Fantasy City Map": "an aerial view of a city, TTRPG city map showing the full city, {prompt}, fantasy art, highly-skilled senior environment artist piece, beautiful fantasy map.",
    "Old World Map": "fantasy world map of {prompt}, fantasy world map, highly detailed digital painting, fantasy art, map illustration, 8k.",
    "3D Isometric Icon": "{prompt}, 3D isometric render of cute {prompt}, 3D app icon, clean isometric design, beautiful design, soft gradient background, soft colors, centered, 3D blender render, masterpiece, best quality, high resolution, 8k octane render, beautiful color scheme, soft smooth lighting, physically based rendering, square image, high polycount",
    "Flat Style Icon": "{prompt}, creative icon, flat style icon, masterpiece, high resolution, crisp, beautiful composition and color choice, beautiful flat painted style, behance contest-winner, award winning icon illustration, 8k, best quality",
    "Flat Style Logo": "beautiful flat-style logo design depicting {prompt}, creative flat-style logo design, trending on dribbble, featured on behance, portfolio piece, minimal flat design, breathtaking graphic design, 8k, high resolution vector logo, plain background, amazingly beautiful logo design, winner of best logo award",
    "Game Art Icon": "{prompt}, a concept art icon for league of legends, a digital art logo, illustration, league of legends style icon, inspired by wlop style, 8k, dota 2 style icon, fine details, sharp, very detailed icon, high resolution rpg ability/spell/item icon",
    "Digital Painting Icon": "{prompt}, app logo icon, digital art pictogram icon, trending on artstation, app icon in the style of atey ghailan, app icon in the style of greg rutkowski, app icon in the style of greg tocchini, app icon in the style of james gilleard, 8k, high resolution, best quality",
    "Concept Art Icon": "{prompt}, a concept art icon, a digital art logo, illustration, league of legends style concept art logo icon, inspired by wlop style, 8k, fine details, sharp, very detailed, high resolution logo icon",
    "Cute 3D Icon": "{prompt}, a cute 3D icon of {prompt}, cartoon 3D icon, very cute shape, stylized octane render, 8k, masterpiece, soooo cute, beautiful cute perfection, beautiful soft lighting, soft colors, centered, high resolution, {prompt}, soft gradient background",
    "Cute 3D Icon 󠀡󠀢󠀡": "{prompt}, a set of lovely little 3D icons, cute 3D icons, very cute shapes, stylized octane render, 8k, masterpiece, soooo cute, beautiful cute perfection, beautiful soft lighting, soft colors, centered, high resolution, {prompt}, cute icon set",
    "Crayon Drawing": "{prompt}, crayon drawing",
    "Pencil": "black and white pencil drawing, {prompt}, black and white, breathtaking pencil illustration, highly detailed, 4k, textured paper, pencil texture, sketch",
    "Tattoo Design": "amazing tattoo design, {prompt}, breathtaking tattoo design, incredible tattoo design",
    "Waifu": "{prompt}, waifu character portrait, 1girl, very high resolution, semi-realistic anime art. Intricate and impressive anime artwork with stunningly beautiful composition and style.",
    "YuGiOh Art": "yugioh card art for {prompt}, art in the style of genzoman, in the style of Akina Fujiwara, in the style of rossdraws, yugioh monster, close up, painterly details, breathtaking art, centered, masterpiece, amazing composition, {prompt}.",
    "Traditional Japanese": "{prompt}, in ukiyo-e art style, traditional japanese masterpiece",
    "Nihonga Painting": "japanese nihonga painting about {prompt}, Nihonga, ancient japanese painting, intricate, detailed",
    "Claymation": "{prompt}, claymation, incredible claymation style, kubo and the two strings style art, Missing Link 2019 art style, clay texture, clay animation, stop-motion clay",
    "Cartoon": "{prompt}, cartoon-style art, superb linework, nice colors and composition, bold linework, masterpiece, cute art in the style of Dana Terrace, in the style of Rebecca Sugar, in the style of ry-spirit, amazing and wholesome cartoon-style art, cute art style, (trending on artstation)",
    "Cursed Photo": "cursed photo of {prompt}, creepy and cursed, absolutely cursed photo, nope nope nope nope, what the actual f, unsettling photo, cursed_thing, cursedimages, no context, cursed image, bad photo, weird photo, very strange, color photo, creepy photo, nightmare fuel",
}

# NOTE: the "Cute 3D Icon <unicode>" key above is the exact key from the
# source styles.json (three mathematical-script characters). It is written
# with explicit \U escapes below to avoid encoding ambiguity; the dict entry
# above is replaced at import time if it did not survive as intended.
_UNICODE_ICON_KEY = "Cute 3D Icon \U0001d5e6\U0001d5f2\U0001d601"
for _k in list(STYLES):
    if _k.startswith("Cute 3D Icon ") and _k != "Cute 3D Icon":
        STYLES[_UNICODE_ICON_KEY] = STYLES.pop(_k)


def list_styles():
    """Return the style names in a stable order."""
    return sorted(STYLES.keys())


def apply_style(style, prompt):
    """Bake a style template into the prompt.

    Same behaviour as the reference wrapper (akashayguta/perchance-image-api):
    ``{prompt}`` is replaced, ``{a|b}`` choice groups resolve to the first
    option, ``[input...]`` fragments are dropped, whitespace is collapsed.
    Unknown/empty style returns the prompt unchanged.
    """
    tpl = STYLES.get(style)
    if not tpl:
        return prompt
    out = tpl.replace("{prompt}", prompt)
    # {option1|option2} -> first option
    out = re.sub(r"\{([^{}]*\|[^{}]*)\}", lambda m: m.group(1).split("|")[0].strip(), out)
    # [input.xxx ...] fragments -> removed
    out = re.sub(r"\[[^\]]*\]", "", out)
    return re.sub(r"\s+", " ", out).strip()
