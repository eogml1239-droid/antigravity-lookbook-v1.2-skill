# Lookbook Image Workflow Prompts (based on the 2026-11-16/17 session)

This document turns the whole process we ran into reusable prompts: model setup, hanger shots, lookbook generation, saving and watermark removal. Each stage has an instruction prompt for Claude and, where relevant, a generation prompt for Gemini. Text in {BRACES} is a placeholder to fill in per product and model.

---

## 0. Standing rules (paste at the start of every lookbook job)

```
Apply the following rules to every lookbook job.
1. Image-generation prompts are always written in English; reports to me are in Korean.
2. Every lookbook request attaches exactly two images: the model photo (Image 1) and the hanger shot of the matching colour (Image 2). Never attach other reference images.
3. Aspect ratio 5:6 portrait. Model and garment tack-sharp edge to edge (f/5.6-f/8). The image must be clean: no film grain, dust, smudges, haze or ghosting.
4. Female models: show only the area below the upper lip (no eyes, nose, forehead or full face). Frame from the upper lip line down to the knees.
5. The gaze must never meet the camera and must look natural. The head direction must differ from cut to cut.
6. The space is a gravity-bound space. Hair hangs down with real weight (no floating strands, no wind, no unnatural volume) and fabric folds follow gravity.
7. Background: the same seamless gray studio wall as the model reference image, flowing into the floor with no horizon line, floor edge or vignette. Poses lean against the wall.
8. Fit: put both the model measurements (height, weight, shoulder, bust, waist, hip) and the garment size-chart numbers (length, chest, shoulder, sleeve) directly in the prompt. Never invent values missing from the size chart. After generation, compare hem, cuff end and shoulder-seam position with the size chart and record it; if they do not match, do not shortlist the image, state why, and regenerate.
9. All cuts of the same colour share one outfit (bottoms, shoes); only the pose changes. Every pose must look clearly different from every other pose; above all vary the head (gaze) direction and the hand positions.
10. Save Gemini images only into the product folder G:\내 드라이브\Claude_산출물\YYYYMMDD_(product name)\ . When a new folder is created, add one line to _INDEX.md. Create files only under G:\내 드라이브\Claude_산출물\ , never on the Desktop.
11. Pass/fail judging is mine. (In a session where I say "no per-cut judging", generate and save everything and let me choose from the final results.)
```

---

## 1. Model registration / replacement

### 1-1. Instruction prompt for Claude
```
Create new lookbook main model N.
- Height and weight are given by me (e.g. Model 1: 164cm/38kg, Model 2: 170cm/50kg, Model 3: 156cm/40kg).
- Choose shoulder, bust, waist, hip, thigh and the look (face shape, hairstyle, impression) to suit the body type, and state clearly that they are generation targets which the image does not prove.
- Background and outfit are identical to Model 4: all-gray studio, fitted white cropped short-sleeve tee + heather gray high-waist bike shorts + barefoot.
- Save the spec table to G:\내 드라이브\Claude_산출물\YYYYMMDD (new model specs)\ and generate the full-body front image in Gemini.
- For approved images, update the lookbook main model folder (G:\내 드라이브\Claude-ChatGPT-Bridge\shared\models\룩북메인모델\모델N\): the image, 스펙.json, 스펙.md, 생성_프롬프트.md and the sha256 in models.json. Back up the existing bundle before replacing it, and delete it only if I tell you to.
- After updating, run load_model.py N and confirm exit code 0.
```

### 1-2. Gemini prompt (full-body model reference)
```
Generate an image: a photorealistic full-body front-facing studio reference photo of a Korean woman, late 20s, {HEIGHT}cm tall, {WEIGHT}kg, {BODY TYPE} (shoulder width {S}cm, bust {B}cm, waist {W}cm, hips {H}cm, thigh {T}cm). {FACE AND HAIR DESCRIPTION}, natural makeup, calm neutral expression. She wears a fitted white short-sleeve cropped t-shirt and heather gray high-waist bike shorts, barefoot. Standing straight, arms relaxed at the sides, feet slightly apart. Setting: all-gray seamless studio, medium gray seamless paper backdrop, slightly darker gray floor, the model standing well in front of the backdrop with clear visible depth and spacing between her and the backdrop, soft frontal studio light with gentle rim separation. Camera: 3:4 portrait, 85mm, eye level, head to feet fully in frame with margin, tack-sharp focus across the whole body and face, crisp detail, moderate depth of field. Realistic skin with visible pores and subtle imperfections, natural hair flyaways, not a CG render. Avoid: blurry, soft focus, motion blur, plastic skin, over-retouched, extra fingers, distorted hands, text, watermark.
```
Follow-up (background fix):
```
Regenerate the same woman with identical face, hair, body, outfit and pose, only changing the background: a true seamless infinity-cove studio where the medium gray backdrop curves smoothly into the floor with no visible horizon line, edge, seam or color break; the wall and floor are the same gray paper with only a soft gradual light-to-dark tonal falloff toward the floor, and a soft natural contact shadow under her feet. Keep 3:4, full body head to feet with feet fully inside the frame, tack-sharp focus, realistic photo.
```
Follow-up (noise removal):
```
Regenerate the same woman with identical face, hair, body, outfit, pose and seamless gray cove background, but make the image extremely clean: remove all film grain, noise, dust specks, smudges, blur, haze, ghosting, double edges and afterimages; a perfectly clean smooth backdrop and floor with a gentle even tonal gradient only, crisp clean edges around the hair, body and clothes with no halo or fringing, clean smooth skin that is still natural, clean crisp fabric. Tack-sharp focus, high-resolution clean studio photograph, 3:4, full body with feet inside the frame.
```

### 1-3. In-house editing (realism optimisation) instruction
```
Optimise model images 1-4 for lookbook generation with our own OpenCV editing tool.
- Remove the bottom-right Gemini star watermark (star-shaped mask + inpainting; where it overlaps the person, recover the pixels by inverting the semi-transparent white overlay).
- Boost high- and mid-frequency detail only inside the skin-colour region so pores and texture come back (do not add noise), and apply a mild local contrast to the person only.
- Smooth the background only in areas at least 60px away from the person and add a soft vignette. If a bright fringe appears around the hair, shrink the affected range and redo it.
- Save candidates first for my review; when approved, replace the callable images, update the sha256, and then delete the previous edited versions.
```

---

## 2. Calling a model

```
Load model N.
- Image/spec: python -I "G:/내 드라이브/Claude-ChatGPT-Bridge/shared/models/룩북메인모델/load_model.py" N --format args  (or --format prompt)
- Attach to Gemini through Google Drive: Attach (+) -> Drive -> type the file name in the search box (e.g. 모델2_최종수정본, 룩북메인모델4) -> select -> Insert.
- The model photo is always attached first and the hanger shot second. (Make the Image 1 / Image 2 labels in the prompt match the attach order.)
```

---

## 3. Getting hanger shots

### 3-1. Downloading existing hanger shots
```
Download the approved hanger shots from the Gemini chat (another session's or mine) per colour and save them in the product folder as hanger_shot_{colour}.png (Korean convention: 행거샷_색상.png).
- If a colour has several versions, choose by the criterion I give (e.g. the one without a dotted stitching line at the neck). If I give none, show the candidates and ask.
- Download by clicking the image, then using the download button in the viewer (original size).
```

### 3-2. Generating a new hanger shot (Gemini, when only a colour chart exists)
```
Image 1 is a color chart of six tops. Use ONLY the {POSITION} one (label {COLOR LABEL}) as the exact reference for color, fabric and design: {COLOR} color, soft thin matte stretch jersey fabric, half-high mock neck made of the same plain fabric with NO decorative stitching, NO trim and NO colored band, long slim sleeves with flat smooth stretch cuffs, side-seam ruched waist detail, slim fit, curved arched hem. Generate ONE image containing TWO hanger shots side by side on a clean plain light gray-white background: the FRONT view on the left and the BACK view on the right, each top hung on its own slim wooden hanger, the same size and aligned at the same height, no model, no text, no logo, soft even daylight, sharp focus everywhere, 5:6 aspect ratio overall. The back view is not visible in the reference, so infer it from the front: plain solid back, back of the half-high neck, same curved hem, side ruching visible at the side seams, no print, no tag visible. Garment is size M (flat-lay measurements): body length 63 cm, chest 80 cm, shoulder width 34 cm, sleeve length 59 cm; in both views the sleeves hang fully straight and extended with the cuff ends clearly below the hem line.
```

---

## 4. Lookbook generation

### 4-1. Outfit and pose plan (Claude writes this table first)
```
Write a table of outfits per colour and poses per cut before generating anything.
- Outfit: choose one bottom per colour and apply it to every cut of that colour (e.g. black = cream slim straight trousers).
- Poses: use the columns [body direction / wall contact] [head and gaze direction] [hand positions], and make sure no two cuts overlap. Vary standing, walking, sitting, crouching, back views and look-backs.
- Check the table for overlaps, then convert it into prompts.
```

### 4-2. Cut 1 Gemini prompt (new chat, after attaching the two images)
```
Generate an image. Image 1 is the model identity reference: keep her skin tone, lips, chin, neck, shoulders, slim body and her {HAIR} exactly; ignore her original clothes, her face is cropped out. Image 2 is a product hanger shot (front left, back right) of the top: use it ONLY as the garment reference and copy the exact {COLOR} colour, {FABRIC AND TEXTURE}, {NECK/SLEEVE/SEAM DETAILS}, slim fit and {HEM}; do not copy its hangers or background. Subject: Korean woman, late 20s, {HEIGHT}cm tall, {WEIGHT}kg, {BUILD} (shoulder {S}cm, bust {B}cm, waist {W}cm, hip {H}cm). She wears the {COLOR} {GARMENT} in size M (flat-lay measurements: body length {L}cm so the hem sits around {HEM POSITION}, chest {C}cm so it fits {FIT DESCRIPTION}, shoulder width {SH}cm {COMPARE TO MODEL SHOULDER}, sleeve length {SL}cm so the sleeves reach {SLEEVE END}), styled with {BOTTOMS}, no jewelry. Pose ({COLOR} 1 of 3): {POSE DESCRIPTION showing the slim waist, bust and hip line}. Gaze and head: her head is turned {DIRECTION} away from the camera and {TILT}, gaze directed {WHERE}, never looking into the lens. Gravity applies in this space: her {HAIR} hangs down with real weight {HOW IT FALLS FOR THIS POSE}, no floating strands, no wind, no unnatural volume; fabric folds also fall with gravity. Background: a plain even medium-light gray seamless studio wall that flows into the floor with NO visible horizon line, NO floor edge, NO baseboard band and NO dark vignette. Lighting: soft frontal studio light with gentle side light that rakes across the fabric so the texture and details are readable. Camera: 5:6 aspect ratio, portrait (e.g. 1000x1200); tack-sharp focus across the model and garment, crisp fabric detail, moderate depth of field (about f/5.6-f/8); 85mm, eye level at chest height; frame cropped at the upper lip line; only the lips, chin, neck and body below are visible; no eyes, nose, forehead or full face in frame; the frame runs from the upper lip line down to the knees so the garment design and fabric read clearly. Realism cues: natural skin texture with visible pores, realistic fabric behaviour with soft natural wrinkles, clean image with no grain, dust or smudges, candid editorial feel, not a CG render. Avoid: blurry, soft focus, motion blur, looking directly at camera, eye contact with the lens, visible eyes, visible nose, forehead, full face, plastic or over-smoothed skin, extra fingers, distorted hands, oversized loose fit, shiny synthetic sheen, floating hair, windblown hair, levitating strands, hair defying gravity, horizon line, floor edge, vignette, text, logo, watermark, noise, ghosting.
```

### 4-3. Cuts 2 and 3 follow-up prompt (same chat)
```
{COLOR} cut {N} of 3, a clearly different pose from the previous cuts. Same model (Image 1), same {COLOR} top (Image 2, same size M numbers: body length {L}cm, chest {C}cm, shoulder {SH}cm, sleeve {SL}cm), same outfit as the other {COLOR} cuts: {BOTTOMS}, no jewelry. Same plain gray seamless wall with no horizon line, 5:6, cropped at the upper lip line down to the knees (no eyes or nose visible). Pose ({COLOR} {N} of 3): {POSE}. Gaze and head: {HEAD DIRECTION AND GAZE}, never looking into the lens. Gravity applies: {HAIR BEHAVIOUR}, no floating strands, no wind. Tack-sharp focus, clean image with no noise, dust or smudges.
```
Correction when the background drifts:
```
The background is wrong. Regenerate the previous look with exactly the same background as Image 1: a plain, even medium-light gray seamless studio wall that flows into the floor with NO visible horizon line, NO floor edge, NO baseboard band and NO dark vignette; the wall and floor are one continuous smooth gray with only a very soft natural tonal gradient and a soft contact shadow, same gray tone and brightness as Image 1. Keep the model, garment, fit numbers, 5:6 framing, tack-sharp focus and clean image unchanged.
```

---

## 5. Pose library (distinct poses used in this job)

| Pose | Body direction / wall contact | Head and gaze | Hands |
|---|---|---|---|
| Whole back flat to the wall, frontal | Frontal, full back on the wall | Turned left, chin slightly raised | Clasped behind the low back |
| Side view, arm raised | One hip and arm touching the wall | Down toward the wall side | One forearm on the wall, other hand in pocket |
| Look-back | 20cm from the wall, twisting over the shoulder | Back toward the wall | Pinching the cuff |
| Facing the wall, back view | Three-quarter back view | Lowered to the right | Both palms flat on the wall |
| Walking along the wall | Mid-step | Ahead in the walking direction | Fingertips trailing along the wall |
| Seated on a stool | Back resting on the wall | Down to the left | Folded on the knee |
| One foot on the wall | Back leaning, knee bent | Up and to the left | Both hands in front pockets |
| One arm behind the head | Standing off the wall | Down to the right | Behind the head / on the hip |
| Seated on the floor, knee up | Shoulder against the wall | Down to the left | Wrist draped over the knee |
| Shoulder lean, arms crossed | Standing side-on, shoulder on the wall | Down to the right | Arms crossed |
| One leg folded against the wall | Back on the wall | Up and to the left | One hand at the collar, one hanging |
| Turning away in mid-step | Just pushed off the wall, rotating | Over the shoulder toward the wall | Sweeping down the opposite sleeve |
| Side-on, hip popped | Leaning lightly on the wall | Right and down | Hand on hip, other hand holding the wrist behind |
| Head tipped back, palms on the wall | Back and shoulder blades on the wall | Up toward the ceiling | Both palms flat on the wall |
| Half-crouch | Low on the heels, back to the wall | Left and lowered | One hand on the knee, one on the floor |

---

## 6. Saving and organising

### 6-1. Product-folder rule
```
Save images downloaded from Gemini into G:\내 드라이브\Claude_산출물\YYYYMMDD_(product name)\ .
- File names: model{N}_{colour}_pose{X}_{description}_v{NN}.png for lookbooks and hanger_shot_{colour}.png for hanger shots.
- When a new folder is created, add one line to _INDEX.md.
- Judging is mine. If I say "no per-cut judging this session", save everything and let me pick from the final results.
```

### 6-2. Auto-save script prompt
```
Write a PowerShell watcher that moves Gemini_Generated_Image*.png from Downloads into the product folder only.
- Move only to the folder written in target.txt; if target.txt is missing or empty, move nothing (never pile everything into one folder).
- Move only finished downloads (no modification for 2 seconds and the file can be opened); if the name exists, append the time. Log moves to autosave.log.
- Save a .ps1 that contains Korean text with a UTF-8 BOM.
- Create a .lnk in the Startup folder so it runs hidden at every boot.
- At the start of each new product, create the product folder and update target.txt.
```
Location: `G:\내 드라이브\Claude_산출물\20261116 (Gemini 자동저장 스크립트)\gemini_autosave.ps1`

### 6-3. Download procedure (Claude operating the Gemini window)
```
Click the image -> viewer -> download (original size) -> wait 25-35 seconds -> in the product folder, rename the most recent Gemini_Generated_Image*.png to the rule-based name. If no file appears, check whether it stayed in Downloads under another name (e.g. the chat title) and move it.
```

---

## 7. Watermark removal

```
Remove the bottom-right Gemini star watermark from the saved lookbook images.
- With our own OpenCV tool, search the bottom-right 260px for a star-shaped area (about 96px) brighter than the background, build a mask and inpaint it.
- If the star overlaps a part of the person such as a finger, do not inpaint; instead estimate the star's semi-transparent alpha as the median over clean cuts and invert it (original = (value - alpha x 255) / (1 - alpha)).
- Save results in a "워터마크제거" subfolder of each folder and keep the originals. Verify with before/after zoom comparisons and report how many files were processed and how many failed.
```

---

## 8. Review and reporting

```
Report in Korean and concisely, with these items:
1. List of generated and saved cuts (colour, model, outfit, pose, file location).
2. Confirmation of the applied rules (ratio, upper-lip crop, gaze away from camera, gravity hair, seamless background, same outfit per colour, distinct poses).
3. Fit comparison: model numbers vs size-chart numbers, and the measured hem / cuff end / shoulder-seam positions. If not measured, write "not measured".
4. Problems (nose visible, smeared fingers, colour drift, etc.) and whether regeneration is needed.
5. Decisions left to me (choosing approved cuts, whether to continue with remaining colours).
Never report "looks fine" from a small screenshot; assert details only after zooming in.
```

---

## 9. Pitfalls found during automation

- Start every Gemini session with a new chat and a hard refresh (Ctrl+Shift+R); do not keep fixing in the same chat, and restart in a new chat after several failures.
- The Drive picker keeps the previous search text and appends to it, so select all and retype every time.
- The position of the "Insert" button in the Drive picker changes with window size; confirm with a screenshot before clicking (a wrong click selects another file).
- When the browser window size changes, coordinate clicks are rejected; take a new screenshot and click again.
- The attach order defines Image 1 / Image 2; if it changes, change the labels in the prompt.
- Claude cannot change Chrome's download location and that setting does not apply to the built-in browser; the auto-save script replaces it.
- Back up before overwriting model images, and delete only when I instruct it.
