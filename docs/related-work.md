# Related work and technical background

Literature review and engineering notes for VisionTouch (projector + one RGB camera touch surface).
Compiled 2026-11-19.

**How to read the evidence tags.** Every reference ends with a tag:

- **[R]** I read the primary text or source code (PDF text, header, source file, or ran the installed library).
- **[A]** I only saw the abstract, a search snippet, or a model-generated page summary. Details are not verified.
- **[U]** Claim is mine (inference or derivation) or could not be checked. Treated as a hypothesis to test on the rig.

Statements marked *(inference)* are not in any cited source.
Local verification used the repo's `.venv` (OpenCV 5.1.0, MediaPipe 1.2.3, NumPy 2.x). No camera was opened.

Sources that could not be fetched: `docs.opencv.org` (HTTP 403), `ti.com` (403), `dl.acm.org` (403), Apple developer docs (JS-only). OpenCV facts therefore come from source headers and `.cpp` files on GitHub.

---

## 1. Hand segmentation in front of dynamic projected content (visible light only)

**Answer.** The published method is *predicted-image background subtraction*: warp the known frame-buffer image into the camera, pass it through a photometric model of the projector, surface and camera, and mark pixels where the camera disagrees [1][2][3][4][6]. The model is a 3×3 **colour mixing matrix** plus per-channel response curves plus an ambient/black-level term. It needs 4 to 6 uniform calibration frames, not hundreds [1][2]. No source handles a *changing camera exposure*. All of them assume a fixed camera response [1] or adapt a per-channel multiplier that is algebraically the same as a gain change [2]. The weakness of plain subtraction is that the hand's **cast shadow** is also "unexpected", giving high recall but poor precision [6]. No software-only polarisation trick exists: the polarisation patents need a polarisation-preserving screen and filters [11].

### Model equations

Nayar et al. [1] (Eq. 3–10), for one screen point and three channels:

```
P_K = p_K( d_K( I_K ) )                       display + projector response, per channel K
C   = V · P                                   camera irradiance (linear), V = 3×3 colour mixing matrix
V_KL = ∫ w_K(λ) s(λ) q_L(λ) dλ                projector band w, surface reflectance s, camera band q
C_L = b_L^-1( m_L^-1( M_L ) )                 undo camera + capture response to get linear value from pixel M
```

- V holds the spectral coupling and does *not* contain the non-linear responses.
- They fix `V_KK = 1`; the scale is absorbed into the projector response.
- Grey-world special case (Eq. 12–13): a single monotonic response `M = h(I)` per pixel, `h = m∘b∘V∘p∘d`.
- The authors note a DLP projector adds a "white" component, a function of R, G, B, so mixing is more complex; the 3×3 model "works as a reasonable approximation" in their experiments (footnote 3).

Fujii, Grossberg and Nayar [2] (Eq. 3–9) add ambient light and a diagonal surface matrix:

```
C = A (F + V P)        A = diag(A_R, A_G, A_B)  surface reflectance in each camera band
                       F = ambient light + projector black level
Ã(t) = A(t) A(0)^-1,   F̃ = A(0) F,   Ṽ = A(0) V        (so  C = Ã (F̃ + Ṽ P))
Ṽ_LK = ΔC_L / ΔP_K                                      (Eq. 5, calibration)
F̃(0) = C − Ṽ P                                          (Eq. 6)
P = Ṽ^-1 ( Ã^-1 C − F̃ )                                 (Eq. 7, what to project for desired C)
Ã_K(t) = C_K(t) / C_K                                    (Eq. 9, one-frame adaptation: measured / desired)
```

The grouping `Ã (F̃ + Ṽ P)` is inferred from Eq. 7; the PDF text extraction dropped the parentheses in Eq. 4 and 8.
For hand segmentation, run it forwards: predicted camera image `Ĉ = Ã (F̃ + Ṽ · lin(I_warped))`. The hand is where `C` differs from `Ĉ`.

### Calibration (patterns and counts)

| Source | Patterns | Count | Notes |
|---|---|---|---|
| Nayar [1] | Uniform images; change one channel at a time | 6 for V (4 suffice, footnote 6); up to 255 grey levels for the response curve (they say fewer, interpolated, is fine, footnote 4) | Per pixel. Needs the camera response known first (chart or multi-exposure). Geometry via 10 binary-coded images (1024 patches). Compensation accuracy: RMS < 3 grey levels. |
| Fujii [2] | Dark uniform + dark with +ΔP in R, G, B | 4 | Projector and camera responses linearised beforehand, off-line. 30 fps compensation, RMS 0.9–3.4 grey levels (Table 2). A (3 numbers per pixel) re-estimated from one frame. |
| Castañeda-Garay et al. [4] | Uniform images at 4 levels, per colour channel | 4 per channel | Verhulst (logistic) transfer `a/(1+e^(−α(z−b))) + k` per channel; sign convention not recoverable from the PDF text. **Local**: one parameter set per region (320×240 regions, camera 640×480, projector 1024×768). Region value = mean of the transfer function over the projector pixels it covers (Eq. 7). Detection: `|E−C| > U` in at least one channel (Eq. 8). Thresholds reported (8-bit scale assumed): local (37, 25, 34), global (60, 62, 60). Detection rate 100 % local vs 41 % global. |
| Jaynes et al. [3] | Same idea for shadow detection: predicted image from frame buffer | Verhulst fit from 4 uniform images (as described in [4]) | I did not read [3] itself; details via [4] and patent US 7,133,083 [3]. |

### Segmenting the hand from the shadow

- Plain predicted-image subtraction "has a high recall but poor precision, verifying that the shadow cast by video projection has great influence" [6]. On 500 images with a pico DLP projector (640×480) and a 648×488 camera, background subtraction took 2.3 ms/frame vs 29.6 ms for their saliency + mean-shift pipeline (parameters `(h_s, h_r, M) = (7, 10, 20)`, confidence threshold Δ).
- Licsár and Szirányi [5] update the stored background from the known projected image, then subtract (abstract only).
- Albedo-contrast segmentation [7] and reflectance modelling [8] are the "reflectance-ratio" family; I only saw their abstracts.
- *(inference)* Ratio test: `R = C / Ĉ` per channel in linear space. Background gives R ≈ 1. Cast shadow gives R < 1 in all channels roughly equally. A hand lit by the projector changes R by channel (skin reflects red more than blue), and a shadow does not. This is a testable way to separate hand and shadow without saliency. Not verified in any source.

### Robustness to auto-exposure and gain

- No primary source addresses a changing camera exposure. [1] needs a fixed response; [2] re-estimates a per-channel multiplier every frame (Eq. 9).
- *(inference)* Treat exposure change as one more multiplicative term. Estimate `g_c = median( C_c / Ĉ_c )` over pixels that were background in the previous frame, divide it out, then threshold. Do this in linear light, after undoing the camera gamma. Lock exposure where possible (section 4); the model is only well-posed if the response is stable.
- *(inference)* Rolling-shutter bands (section 3) are also multiplicative, so a per-row gain `g_c(y)` from the same robust ratio covers them.

### Other no-extra-hardware tricks

- **Polarisation**: cross-polarised projector and camera filters remove the projected image, but the patents assume a polarisation-preserving screen and the hand then shows bright against dark [11]. A diffuse wall depolarises light, so the idea does not work on an ordinary wall, and it needs filters. Not applicable here.
- **Camera-synchronised imperceptible patterns**: exploit the DLP mirror-flip timing so a short exposure sees a chosen binary pattern [9][10]. Requires an externally triggered camera; webcams and phones cannot do this.
- **IR**: excluded by the project constraints, but note that PlayAnywhere avoids the whole problem with an IR-pass filter [13].

### References

1. S. K. Nayar, H. Peri, M. D. Grossberg, P. N. Belhumeur. *A Projection System with Radiometric Compensation for Screen Imperfections.* IEEE Int. Workshop on Projector-Camera Systems (PROCAMS), 2003. https://www.cs.columbia.edu/CAVE/publications/pdfs/Nayar_PROCAMS03.pdf **[R]**
2. K. Fujii, M. D. Grossberg, S. K. Nayar. *A Projector-Camera System with Real-Time Photometric Adaptation for Dynamic Environments.* CVPR 2005. https://www1.cs.columbia.edu/CAVE/publications/pdfs/Fujii_CVPR05.pdf **[R]**
3. C. Jaynes, S. Webb, R. M. Steele. *Camera-Based Detection and Removal of Shadows from Interactive Multiprojector Displays.* IEEE TVCG 10(3):290–301, 2004. doi:10.1109/TVCG.2004.1272728. https://pubmed.ncbi.nlm.nih.gov/18579960/ ; related patent US 7,133,083 B2 https://patents.google.com/patent/US7133083B2/en **[A]**
4. M. Castañeda-Garay, Ó. Belmonte-Fernández, H. Pérez-Rosés, A. Díaz Tula. *Detection of Non-Stationary Photometric Perturbations on Projection Screens.* J. Research and Practice in Information Technology 44(4), 2012 (arXiv:1411.6275). https://arxiv.org/abs/1411.6275 **[R]**
5. A. Licsár, T. Szirányi. *Hand Gesture Recognition in Camera-Projector System.* Computer Vision in HCI (ECCV 2004 workshop), Springer, 2004. https://link.springer.com/chapter/10.1007/978-3-540-24837-8_9 **[A]** (venue as cited by [6])
6. J. Dai, R. Chung. *Combining Contrast Saliency and Region Discontinuity for Precise Hand Segmentation in Projector-Camera System.* ICPR 2012, pp. 2161–2164. http://jwdai.github.io/Publications/jwdai-ICPR12.pdf **[R]**
7. M. He, J. Cheng, W. Feng. *Real-time albedo contrast-based hand segmentation in projector-camera system.* IEEE ROBIO 2014. doi:10.1109/ROBIO.2014.7090453. https://ieeexplore.ieee.org/document/7090453 **[A]**
8. A. Mustafa, K. S. Venkatesh. *Background Reflectance Modeling for Robust Finger Gesture Detection in Highly Dynamic Illumination.* ICHIT 2011, LNCS 6935:748–761. https://www.researchgate.net/publication/221416385 **[A]**
9. D. Cotting, M. Näf, M. Gross, H. Fuchs. *Embedding Imperceptible Patterns into Projected Images for Simultaneous Acquisition and Display.* ISMAR 2004, pp. 100–109. https://ieeexplore.ieee.org/document/1383047/ **[A]**
10. D. Cotting, M. Naef, M. Gross, H. Fuchs. *Imperceptible Patterns for Reliable Acquisition of Mixed Reality Environments.* WIAMIS 2005. https://cgl.ethz.ch/Downloads/Publications/Papers/2005/Cot05/Cot05.pdf **[R]**
11. US 9,297,942, *Imaging with polarization removal* (assignee not verified). https://image-ppubs.uspto.gov/dirsearch-public/print/downloadPdf/9297942 **[A]**; also US 9,454,241 *Interactive polarization-preserving projection display* https://image-ppubs.uspto.gov/dirsearch-public/print/downloadPdf/9454241 **[A]**
- Also used: [13] (PlayAnywhere, listed in section 2).

---

## 2. Touch vs hover from the finger's shadow with one camera

**Answer.** PlayAnywhere [13] separates shadow from hand with a **fixed threshold** on an IR image, because the IR-pass filter removes the projected image. It takes the topmost point of each shadow blob that enters from the image bottom as the fingertip, and decides contact by **thresholding the width of the shadow just below the fingertip** (a touching finger occludes its own shadow). It gives no numeric threshold. Accuracy is about 3–4 mm (≈4.5 px of a 640×480 image) at 30 Hz. Later work uses the **distance between finger and shadow tip** [15] or the **distance between two shadows** from two lamps [14]. Visible-light variants exist [16][17] but I could only read abstracts. The camera must be displaced from the light source; a coaxial arrangement cannot give hover [13].

### PlayAnywhere algorithm (read from the paper [13] and patent [14b])

1. Hardware: NEC WT600 DLP short-throw projector (1024×768), grayscale camera (640×480, 2.9 mm wide-angle lens) mounted near the top of the projector with an oblique view, IR-pass filter on the camera, IR LED illuminant placed *off axis from the camera* "so that objects above the surface generate controlled shadows indicating height". Camera and illuminant are rigidly attached to the projector, so calibration to the display is the same everywhere.
2. Rectify: undistort and homography-warp the camera image to the display.
3. Shadow image: "a simple thresholding operation" of the rectified IR image. No threshold value and no background subtraction are given.
4. Fingertip candidate: the highest point (closest to the device) of each connected component of the smoothed shadow image that enters from the bottom edge (away from the device). This rejects other objects.
5. Touch: "we simply threshold the width of the finger shadow computed at a location slightly below the topmost point". Figure 7: "A finger on the surface occludes almost all of its own shadow, while a finger above the surface does not." The paper suggests adding a verification step (not implemented).
6. Hover/height: "it should be possible to calculate the exact height of the finger over the surface if the finger and its shadow are matched ... and tracked", but they do not do it. The UI demo uses hover from the shadow width.

Stated limits:
- One finger per hand.
- Dark objects on the table count as shadow and corrupt detection if nearby; pointy dark objects reaching the bottom of the image cause false positives.
- The surface must reflect IR, and the lamp must be "significantly brighter than stray infrared".
- Resolution drops far from the unit.
- The algorithm "will sometimes report touch when the finger is some millimeters above the surface", and the authors recommend a depth or capacitive sensor if touch sensing is all that is needed.
- 30 Hz frame rate with all features on, CPU only.

### Variants

| Source | Light | Decision rule | Comment |
|---|---|---|---|
| Hitachi Maxell US 9,367,176 [14] | Two lamps at different positions | Two shadows per finger. Brightness threshold `L_th` on a background-subtracted image gives shadow regions; contours of each shadow; touch when the distance between the two contours falls below a threshold. Using the *outer* sides of the shadows improves accuracy; lamps can alternate per frame. | Patent; read abstract and summary. Prior art cited: touch when the distance between the finger's real image and its shadow is below a threshold (JP 2011-180712). |
| Dung, Lai, Wu, ICASSP 2013 [15] | IR | Distance between fingertip and shadow tip, tip directions, and an approach-distance accumulator over frames | Reported 97.53 % detection at 10 px tolerance. Abstract only. |
| Song et al., JSID 2017 [16] | Visible, single camera and projector | Camshift fingertip tracking plus finger-to-surface distance estimated from finger and shadow | Abstract only. |
| VIRTOS [17] | Visible, single camera | Area of the hand's shadow becomes very small at a button; ratio of finger and shadow regions | Search snippet only; authors not verified. |

### Offset and geometry

- Shadow cast by the *projector* lies on the line from the projector through the fingertip. A camera on the same line sees the shadow hidden behind the finger, so no hover information: PlayAnywhere's related work says the coaxial-illuminant approach "is unable to infer precise depth or hover information" [13]. For this rig the near-projector camera is therefore unsuitable for shadow-based hover; the side phone (1–1.5 m off axis) is suitable.
- *(inference, derivation)* A point at height `h` above the wall casts its shadow displaced on the wall by `d = h · tan α`, `α` being the angle between the projector ray and the wall normal at the finger. For `h = 5 mm`, `α = 30°`: `d ≈ 2.9 mm`. That is the number of camera pixels you need to resolve (PlayAnywhere: 3–4 mm ≈ 4.5 px). The required offset follows from the camera's pixel footprint on the wall. No source states a minimum baseline.
- *(inference)* Failure cases specific to this project, not discussed in the IR papers: (a) the shadow exists only where projected content is bright, so dark UI regions give no shadow; (b) ambient light fills the shadow in a lit room; (c) projected content edges can mimic a shadow edge unless you work on the ratio `C/Ĉ` from section 1.

### References

13. A. D. Wilson. *PlayAnywhere: A Compact Interactive Tabletop Projection-Vision System.* UIST 2005. https://www.microsoft.com/en-us/research/wp-content/uploads/2016/10/Wilson-PlayAnywhere-UIST-2005.pdf **[R]**
14. T. Matsubara, S. Narikawa, N. Mori (Hitachi Maxell). *Operation detection device, operation detection method and projector.* US 9,367,176 B2. https://patents.google.com/patent/US9367176B2/en **[R]** (abstract + summary)
14b. A. D. Wilson, S. Bathiche (Microsoft). *Compact interactive tabletop with projection-vision.* US 7,599,561 B2. https://patents.google.com/patent/US7599561B2/en **[R]** (description; I did not read the claim text. Claims 7–8 per a paraphrase: shadow analysis component decides touching or hovering from binarised shadow images.)
15. L.-R. Dung, G.-Y. Lai, Y.-Y. Wu. *Shadow Touching for Interactive Projectors.* ICASSP 2013, pp. 1798–1802. doi:10.1109/ICASSP.2013.6637962. https://ieeexplore.ieee.org/document/6637962/ **[A]**
16. Song et al. (full author list not verified). *A robust projector–camera interactive display system based on finger touch control by fusing finger and its shadow.* J. Soc. Inf. Display, 2017. https://sid.onlinelibrary.wiley.com/doi/abs/10.1002/jsid.608 **[A]**
17. *Virtual touch screen "VIRTOS": Implementing virtual touch buttons and virtual sliders using a projector and camera.* VISAPP 2014. https://www.scitepress.org/Papers/2014/47286/pdf/index.html **[A]** (landing page only fetched)

---

## 3. Rolling-shutter colour banding with DLP/laser projectors

**Answer.** A single-chip DLP projector shows colours *in sequence*: a colour wheel at about 120 Hz for the unit measured in [18] (R, G, B segments), with the DMD modulating each pixel's brightness by binary mirror flips at around 10 kHz [18][10]. A camera that is not synchronised sees this as strobing [18]. A rolling-shutter sensor exposes each row at a slightly later time, so each row integrates a *different slice of the colour sequence*, producing coloured horizontal bands that drift from frame to frame. Laser/LED sequential-colour projectors behave the same way (the colour field order is the strobing; not verified for laser). I found no TI document that gives wheel speeds or banding guidance (`ti.com` blocked automated fetching); the only measured numbers are from [18] and [10].

### Model *(derivation, standard integration argument)*

Row `y` is exposed from `t0 + y·τ` to `t0 + y·τ + T` (`τ` = row readout time, `T` = exposure). Its value in colour channel `c` is

```
I_c(y) = ∫ L_c(t) dt  over [t0 + yτ,  t0 + yτ + T]
```

If `L_c(t)` is periodic with period `P` (one full R-G-B sequence, i.e. one projector frame) and `T = k·P` for an integer `k`, the integral is the same for every row, and the banding vanishes. If not, the bands have a spatial period of `P/τ` rows, and amplitude falls as `T` grows relative to `P`. For `T < P` you can only correct afterwards.

### Mitigations available from software

| Mitigation | Status | Notes |
|---|---|---|
| Set exposure to an integer multiple of the projector frame period (1/60 s, 1/30 s, ...) | needs exposure control (section 4) | Secondary sources (vendor notes, a patent on flicker detection, US 9,838,622) agree on the integer-multiple rule [U]. In a dim room auto-exposure will pick a long exposure anyway; the problem is that bright content makes it pick a short one. |
| Average several frames | *(inference)* | The band pattern drifts relative to the frame; averaging N frames reduces amplitude roughly with N if bands are uncorrelated. Costs N frames of latency, so apply only to the *reference* (background), not to the live frame. |
| Luminance-only or green-channel processing | *(inference)* | The green/pink banding is a chrominance effect (channel imbalance across rows). Y or G reduces it but does not remove it. |
| Per-row, per-channel gain correction | *(inference)* | `g_c(y) = trimmed-median_x( C_c(x,y) / Ĉ_c(x,y) )`, smoothed over `y` and time, divided out before thresholding. Works because the predicted image already holds the expected content; the hand is a minority of any row. |
| Android antibanding (`CONTROL_AE_ANTIBANDING_MODE`) | no | Targets mains flicker (50/60 Hz) only [29]. |
| Hardware sync (trigger camera to the DMD) | not available | This is how [9][10] get stable images. Webcams and phones cannot do it. |

Measured facts available for tuning: an unsynchronised DLP projector acts like a strobe at "10000 Hz, due to the DMD chip, and at 120 Hz, due to the colorwheel" [18]. For one tested projector the mirrors do not flip during a 0.4–0.5 ms window per frame [10] (useful only for triggered cameras). The wheel speed differs between projectors, so measure yours: film a white frame at a short exposure and read the band period `P/τ` from the image.

### References

18. S. J. Koppal, S. G. Narasimhan. *Illustrating motion through DLP photography.* PROCAMS workshop paper (year not verified). http://www.cs.cmu.edu/~ILIM/projects/IM/procams%20webpage/procams_4.pdf **[R]** (abstract and introduction). Journal version: S. J. Koppal, S. Yamazaki, S. G. Narasimhan, *Exploiting DLP Illumination Dithering for Reconstruction and Photography of High-Speed Scenes*, IJCV 96(1):125–144, 2012, doi:10.1007/s11263-011-0454-y **[A]**
- Refs 9 and 10 (Cotting et al.) and 29 (Android Camera2) are listed in sections 1 and 4.
- Patent US 9,838,622 *Flicker detection using semiconductor light source*, https://image-ppubs.uspto.gov/dirsearch-public/print/downloadPdf/9838622 **[A]** (only the integer-multiple statement was seen, in a search summary).

---

## 4. Camera control from Python

**Answer.** On macOS OpenCV's AVFoundation backend implements **only width, height and FPS**: no exposure, gain, or white balance [22]. Windows (MSMF, DSHOW) and Linux (V4L2) do expose exposure, with different units and conventions. For a UVC webcam on macOS, `uvc-util` and `uvcctl` can lock exposure out-of-band via IOKit, but not for the built-in FaceTime camera. For the phone, scrcpy has **no** exposure, ISO or white-balance option in any release; one open, unreviewed pull request would add them. Latency is controlled by always reading the newest frame and, on Linux, `CAP_PROP_BUFFERSIZE`.

### Per-backend property support (from OpenCV source)

| Property | AVFoundation (macOS) | MSMF (Windows) | DSHOW (Windows) | V4L2 (Linux) |
|---|---|---|---|---|
| FRAME_WIDTH/HEIGHT/FPS | yes (set both W and H) | yes | yes | yes (FPS via `VIDIOC_S_PARM`, default 30) |
| FOURCC | no | yes (set) | – | yes (set; resets stream) |
| EXPOSURE | **no** | yes, `IAMCameraControl::Exposure`, set with manual flag | yes, raw value to `CameraControl_Exposure` (partly read) | yes, `V4L2_CID_EXPOSURE_ABSOLUTE` |
| AUTO_EXPOSURE | **no** | yes; any non-zero value means *auto* (code: `value != 0 ? Auto : Manual`) | yes; value 1 = auto (partly read, [A]) | yes, `V4L2_CID_EXPOSURE_AUTO` |
| GAIN | no | yes, `VideoProcAmp_Gain` (manual flag only, no auto-gain property) | – | yes, `V4L2_CID_GAIN` |
| AUTO_WB / WB_TEMPERATURE | no | **not handled** (set returns false, get −1); `CAP_PROP_TEMPERATURE` maps to white balance | – | yes (`V4L2_CID_AUTO_WHITE_BALANCE`, `..._TEMPERATURE`) |
| BUFFERSIZE | no | set returns false; internal queue of 3 that drops old frames | – | yes, 1–10 (default 4), resets stream |
| Driver dialog (`CAP_PROP_SETTINGS`) | no | no | **yes** ("only supported by DSHOW backend currently") | no |

Sources: `cap_avfoundation_mac.mm`, `cap_msmf.cpp`, `cap_v4l.cpp` (4.x branch; the 5.x AVFoundation file was re-read and has no `EXPOSURE` match), `cap_dshow.cpp` (5.x, partly read), `videoio.hpp` (5.x) [22].

Units and conventions:
- **V4L2**: `EXPOSURE_ABSOLUTE` is in 100 µs units ("1 stands for 1/10000th of a second") and "is limited by the frame interval". `EXPOSURE_AUTO` enum names per the kernel docs: `AUTO` (auto time, auto iris), `MANUAL` (manual time, manual iris), `SHUTTER_PRIORITY`, `APERTURE_PRIORITY` (auto time, manual iris) [23]. The page I read gives names, not numbers; the numeric values 0/1/2/3 are from the kernel header (from memory) and agree with OpenCV's normalised mapping 0.25→1, 0.75→3 [22]. So `set(CAP_PROP_AUTO_EXPOSURE, 1)` selects manual and `3` is the usual auto mode. Set manual first, then the value. `EXPOSURE_AUTO_PRIORITY` lets the device lower the frame rate in the dark; it is disabled by default [23]. The old `0.25/0.75` values only apply when `OPENCV_VIDEOIO_V4L_RANGE_NORMALIZED` is set (default false in the source; the code comment says "enabled by default", the code itself disagrees). In normalised mode `AUTO_EXPOSURE` uses `Range(0,4)`, so 0.25→1 and 0.75→3 [22].
- **DirectShow / MSMF**: Microsoft defines exposure as log base 2 of seconds: negative `n` means `1/2^|n|` s; −3 is 1/8 s [24]. OpenCV passes the raw value through; no unit is mentioned in OpenCV's code.
- **OpenCV 5.0**: unsupported properties now return **−1** from `VideoCapture::get` (4.x AVFoundation returned 0). Check `val < 0` [30].
- The installed `cv2` 5.1.0 exposes `CAP_PROP_AUTO_EXPOSURE=21`, `CAP_PROP_EXPOSURE=15`, `CAP_PROP_BUFFERSIZE=38`, and on this Mac only the `AVFOUNDATION`, FFMPEG, GStreamer, MJPEG and uEye backends. [R, ran locally]
- Always read back after `set()`: `set()` returns true when the backend *has* the property, not when the device accepted the value (`videoio.hpp`) [22].

### Locking exposure on macOS

- **Built-in FaceTime camera**: OpenCV cannot. The only route is `AVCaptureDevice.exposureMode = .locked` or `.custom` through AVFoundation; whether the Apple-silicon built-in camera reports `isExposureModeSupported(.locked)` as true is **unverified** (Apple docs not readable; `SableRaf/lockFacetimeAutoExposure` tests this at runtime and bails out if unsupported [27]). `uvcctl` states that built-in laptop cameras "usually aren't UVC devices" and are not supported [26]. Run a 20-line PyObjC probe once on the rig to find out; I did not, since I must not open the camera.
- **UVC webcams (external)**: `jtfrey/uvc-util` (MIT, IOKit, last commit 2024-02-26, build with `gcc`; an issue about `auto-exposure-mode` on some cameras is closed, and issue #14 reports "finds UVC devices but no capabilities" on Monterey, closed 2022-08-09) [25]. A vendor note shows `uvc-util -I 0 -s auto-exposure-mode=1` then `-s exposure-time-abs=50` (unit 100 µs) [A]. `tapsterbot/uvcctl` (MIT, Go, macOS universal arm64/x86_64, Linux, Windows; v0.1.0, Nov 2026) has `uvcctl lock [--settle 4s]`: auto modes run, settle, then are switched off. Its README warns that on at least one camera the locked values revert when the stream restarts, and settings are lost on power loss; use `set` then `save`/`load --watch` [26]. Exposure unit: 0.1 ms on macOS/Linux, log2 s on Windows. Neither tool was run here [U].
- **Windows**: `cap.set(cv2.CAP_PROP_SETTINGS, 1)` on `CAP_DSHOW` opens the driver property page where exposure can be fixed by hand [22].

### Android phone via scrcpy

- Camera options (official docs, read from the repo and the man page) [28]: `--video-source=camera` (Android 12+), `--camera-id`, `--camera-facing=front|back|external`, `--camera-size=WxH`, `--camera-ar`, `-m/--max-size`, `--camera-fps`, `--camera-high-speed` (restricted to the sizes and rates in `--list-camera-sizes`; example `--camera-size=1920x1080 --camera-high-speed --camera-fps=240`), `--list-cameras`, `--list-camera-sizes`, `--camera-torch`, `--camera-zoom` (added in 4.0), `--orientation`. Sizes and rates are "declarative. They are not accurate on all devices".
- **No exposure, ISO, white-balance, focus or AE-lock option exists in any released version.** PR #6960 (open since 2026-07-26, one commit, no reviews, author discloses LLM-assisted edits) proposes `--camera-iso`, `--camera-exposure` (nanoseconds; title says ms) and `--camera-awb-lock`; issue #6592 asks for it (open) [28].
- Android's Camera2 API has the controls (`CONTROL_AE_LOCK`, `CONTROL_AWB_LOCK`, `SENSOR_EXPOSURE_TIME`, `SENSOR_SENSITIVITY`, `CONTROL_AE_MODE`) [29]; scrcpy just does not expose them. The workaround of a different Android camera app that locks them is **unverified**.
- **Version check**: the task brief says scrcpy 4.x. The releases page I read lists **v5.0.1 (08 Oct)** as latest, v5.0 (05 Oct), v4.1 (12 Jul), v4.0 (12 May); years are inferred as 2026. v5.0 notes: hardware decoding (`--hwdec`), "Improve video buffering". Camera mode is single camera per session. [28]
- Getting frames into OpenCV: the documented route is `--v4l2-sink` with v4l2loopback, **Linux only**; for macOS and Windows I found nothing in the official docs [28].

### Minimising capture latency

- **macOS (AVFoundation backend)**: `alwaysDiscardsLateVideoFrames = YES` is set in OpenCV's source, so frames are dropped, not queued; session preset is `AVCaptureSessionPresetMedium`, output BGRA→BGR; no buffer property [22].
- **Windows MSMF**: internal queue of 3 frames dropping old ones; `OPENCV_VIDEOIO_MSMF_ENABLE_HW_TRANSFORMS=0` "may improve initialization time" (documented in `videoio.hpp`) [22]. Set FOURCC to MJPG to get 720p/1080p at 30 fps over USB 2 *(inference)*.
- **Linux V4L2**: `cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)` (accepts 1–10, resets the stream) [22].
- **All**: *(inference)* a reader thread that overwrites a single "latest frame" slot, so the processing loop never consumes stale frames. Record `time.monotonic()` immediately after `read()` returns.
- **scrcpy**: no video buffering by default ("to get the lowest possible latency"); `--video-buffer` adds delay; the README claims 35–70 ms for display mirroring (camera path not measured by the project) [28].

### References

22. OpenCV source (4.x and 5.x branches): https://github.com/opencv/opencv/blob/4.x/modules/videoio/src/cap_avfoundation_mac.mm ; https://github.com/opencv/opencv/blob/4.x/modules/videoio/src/cap_msmf.cpp ; https://github.com/opencv/opencv/blob/4.x/modules/videoio/src/cap_v4l.cpp ; https://raw.githubusercontent.com/opencv/opencv/5.x/modules/videoio/src/cap_dshow.cpp ; https://raw.githubusercontent.com/opencv/opencv/5.x/modules/videoio/include/opencv2/videoio.hpp **[R]** (DSHOW and the second half of `videoio.hpp` only partly read)
23. Linux kernel documentation, *Camera Control Reference* (`V4L2_CID_EXPOSURE_AUTO`, `V4L2_CID_EXPOSURE_ABSOLUTE`). https://www.kernel.org/doc/html/latest/userspace-api/media/v4l/ext-ctrls-camera.html **[R]**
24. Microsoft Learn, *CameraControlProperty enumeration* (exposure in log base 2 seconds). https://learn.microsoft.com/en-us/previous-versions/ms779747(v=vs.85) **[A]**
25. J. Frey. *uvc-util*, MIT. https://github.com/jtfrey/uvc-util **[A]**
26. Tapster Robotics. *uvcctl*, MIT. https://github.com/tapsterbot/uvcctl **[A]**
27. S. Raf. *lockFacetimeAutoExposure*. https://github.com/SableRaf/lockFacetimeAutoExposure **[A]**
28. Genymobile. *scrcpy* docs: https://github.com/Genymobile/scrcpy/blob/master/doc/camera.md (re-read locally), https://github.com/Genymobile/scrcpy/blob/master/doc/video.md , https://github.com/Genymobile/scrcpy/blob/master/doc/v4l2.md , https://github.com/Genymobile/scrcpy/blob/master/app/scrcpy.1 , releases https://github.com/Genymobile/scrcpy/releases , PR https://github.com/Genymobile/scrcpy/pull/6960 , issue https://github.com/Genymobile/scrcpy/issues/6592 **[R]** (docs) / **[A]** (PR and issue pages)
29. Android Developers, *CaptureRequest* (Camera2). https://developer.android.com/reference/android/hardware/camera2/CaptureRequest **[A]**
30. OpenCV wiki, *OpenCV 4 to 5 migration* ("unsupported properties return -1", PR #21337). https://github.com/opencv/opencv/wiki/OpenCV-4-to-5-migration **[A]**

---

## 5. MediaPipe Hands in this setting

**Answer.** Use the Tasks `HandLandmarker`. In the installed `mediapipe` **1.2.3**, `mp.solutions` does **not exist** (checked by import in the repo's `.venv`): the legacy `mp.solutions.hands` is gone, only `mp.tasks` and `mp.Image` remain. The official guide covers one model, `hand_landmarker.task`, downloaded separately from Google Cloud Storage. Published accuracy is about 5 % of palm size (normalised mean error) on the model card's data, with an explicit warning that it was *not tested in low light or with motion blur*. No primary source covers upscaling, gamma or CLAHE; the only documented tricks are ROI cropping and confidence thresholds.

### API (docs plus local introspection, mediapipe 1.2.3)

PyPI: 1.2.3 released 2026-11-11, Apache-2.0, classifiers list Python 3.9–3.14, `py3-none` wheels for macOS arm64 only (no Intel Mac), Windows amd64/arm64, manylinux_2_28 x86_64/aarch64 [31]. The model card also says "Licensed under Apache License, Version 2.0" [33].

```python
import mediapipe as mp
import cv2

BaseOptions = mp.tasks.BaseOptions
HandLandmarker = mp.tasks.vision.HandLandmarker
HandLandmarkerOptions = mp.tasks.vision.HandLandmarkerOptions
RunningMode = mp.tasks.vision.RunningMode

options = HandLandmarkerOptions(
    base_options=BaseOptions(model_asset_path="hand_landmarker.task"),
    running_mode=RunningMode.VIDEO,          # IMAGE (default) | VIDEO | LIVE_STREAM
    num_hands=1,                             # default 1
    min_hand_detection_confidence=0.5,       # defaults all 0.5
    min_hand_presence_confidence=0.5,        # below this in VIDEO/LIVE_STREAM -> palm detector re-runs
    min_tracking_confidence=0.5,             # docs: bounding-box IoU between consecutive frames
)
with HandLandmarker.create_from_options(options) as lm:
    rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
    img = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
    res = lm.detect_for_video(img, timestamp_ms)   # int, strictly increasing
    # res.hand_landmarks, res.hand_world_landmarks, res.handedness
```

Verified signatures in 1.2.3: `detect(image, image_processing_options=None)`, `detect_for_video(image, timestamp_ms, image_processing_options=None)`, `detect_async(image, timestamp_ms, ...) -> None`; `result_callback(result, output_image, timestamp_ms)` is only for `LIVE_STREAM`.
- `detect_for_video` is synchronous and processes every frame in order; `detect_async` "may drop the input images if needed" so output stays current [31].
- Timestamps must increase monotonically; `detect_async` raises `ValueError` otherwise.
- `image` can be any size, RGB or RGBA. Handedness refers to the subject's hands: "Passing a horizontally mirrored image will invert these outputs" [31].
- Release notes for 1.2.3 mention "unify ... option, method, and result names across Python, Web, Android, and iOS while preserving deprecated compatibility aliases": names may drift [31].
- Model download (official guide): `https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/latest/hand_landmarker.task`. Only one variant ("full", float16, inputs listed as 192×192 and 224×224) is documented [31]. The older `float16/1/` path is from memory and unverified.
- Latency on a Pixel 6 (full model): 17.12 ms CPU, 12.27 ms GPU [31]. No desktop numbers are published.

### Accuracy and its limits

- Model card [33]: error is normalised by palm size (wrist to middle-finger MCP). Human re-annotation baseline: 3.8 % MNAE. Full model across six skin tones: 5.08 % ± 0.72 (lite: 5.67 %). Error is larger for blurry or occluded joints. **Limitation stated verbatim**: "The model has not been tested in 'in-the-wild' smartphone camera conditions, including low-end devices, low light, motion blur etc., that can affect performance", and quality "can degrade in extreme conditions".
- Paper [32]: palm detector then landmark model; the landmark model's "Full" variant has MSE 10.05 (% of palm size) at 16.1 ms (Pixel 3), 11.1 ms (Galaxy S20), 5.3 ms (iPhone 11). Training mix: real plus synthetic ("combined" 13.4 % vs 16.1 % real-only for the ablation in the paper's Table 2).
- The docs state ≈30K real images plus synthetic hands [31]. Nothing in the docs or model card covers *small or distant hands*.
- Evidence on tricks: (a) ROI cropping improves detection when hands are small in a full-body frame (freemocap PRs #85/#885; "works fine but is still not as good as the Holistic version") [34]; (b) the hand ROI heuristic assumes a hand plane parallel to the camera [36]; (c) users report poor results on IR images because the model was trained on natural light [35]. I found *no* source on upscaling crops, gamma or CLAHE.
- *(inference)* Plan for this project: use the segmentation mask from section 1 to crop the hand with margin, upscale to roughly 256 px, and call `detect()` (IMAGE mode, no tracking state) on the crop, since cropping changes the frame between calls and invalidates VIDEO-mode tracking. Map landmarks back through the crop transform. Test gamma and CLAHE on recorded rig footage; the projector's coloured light on the hand is outside the training distribution [U].

### References

31. Google AI Edge. *Hand landmarks detection guide*, Python API reference (`HandLandmarker`, `HandLandmarkerOptions`), release notes, PyPI. https://developers.google.com/edge/mediapipe/solutions/vision/hand_landmarker ; https://developers.google.com/edge/api/mediapipe/python/mp/tasks/vision/HandLandmarkerOptions ; https://developers.google.com/edge/api/mediapipe/python/mp/tasks/vision/HandLandmarker ; https://pypi.org/project/mediapipe/ ; https://github.com/google-ai-edge/mediapipe/blob/master/mediapipe/tasks/python/vision/hand_landmarker.py **[R]** (plus API checked by import in the installed 1.2.3)
32. F. Zhang, V. Bazarevsky, A. Vakunov, A. Tkachenka, G. Sung, C.-L. Chang, M. Grundmann. *MediaPipe Hands: On-device Real-time Hand Tracking.* arXiv:2006.10214 (CVPR Workshop on Computer Vision for AR/VR 2020). https://arxiv.org/abs/2006.10214 **[R]** (arXiv version; workshop venue from memory, unverified)
33. Google. *Model Card: Hand Tracking (Lite_Full) with Fairness*, Oct 2021. https://storage.googleapis.com/mediapipe-assets/Model%20Card%20Hand%20Tracking%20(Lite_Full)%20with%20Fairness%20Oct%202021.pdf **[R]**
34. freemocap/skellytracker PR #85 and freemocap PR #885, *Mediapipe Hand Detection Upgrade using ROI Cropping*. https://github.com/freemocap/freemocap/pull/885 **[A]**
35. google-ai-edge/mediapipe issue #6118, *Using IR camera for hand landmark tracking*. https://github.com/google-ai-edge/mediapipe/issues/6118 **[A]**
36. *Optimizing Hand Area Detection in MediaPipe Holistic Full-Body Pose Estimation* (code: https://github.com/sign-language-processing/mediapipe-hand-crop-fix ; paper arXiv:2405.03545). https://arxiv.org/abs/2405.03545 **[A]**

---

## 6. Geometric calibration: projector → camera homography

**Answer.** For a planar wall, a single homography `H` (camera ← projector) from point correspondences is enough, and the old PROCAMS papers report ≤ 0.6 px max / 0.19 px RMS (display pixels) with 10 binary-coded images [1] and 0.54 px RMS for a coaxial rig [2]. A **projected ChArUco/ArUco grid** gives a one-frame, ID-labelled, partial-occlusion-tolerant correspondence set; **Gray code** gives dense correspondences, is robust to decoding errors, but needs a static scene and 2·log2(N) frames [39]. Camera lens distortion must be removed first, or it ends up inside `H`. To detect movement, re-check the homography against known fiducials and recalibrate when the residual rises; Sukthankar et al. do exactly that [40].

### Expected error (published)

| Source | Method | Error |
|---|---|---|
| Nayar [1] | Piecewise 2nd-order polynomials (16 blocks), 1024 patches via 10 binary images | max 0.6, RMS 0.19 display pixels (800×600 projector, 640×480 camera) |
| Fujii [2] | Binary-coded checkerboards, coaxial rig | RMS 0.54 px |
| Moreno & Taubin [39] | Gray code + a **local homography per checkerboard corner** | projector reprojection 0.1447 px; global homography 0.2176 px; a prior toolbox 0.8671 px (the camera value 0.3288 px is read from extracted table text). Camera was 4272×2848, projector 1024×768, so **not transferable to a webcam**. Projector lens distortion is real: points near a corner are displaced about 12 px; `k1 = −0.0888, k2 = 0.3365` |
| Sukthankar et al. [40] | Bright rectangle then circle slides, 160×120 camera | ±3 px on a 1024×768 slide for pointer detection at 20 Hz |
| This rig (synthetic check) | ChArUco 9×6 rendered at 1080×720, `findHomography` | 0.40 px RMS with *no* distortion and no corner refinement (local run, floor of the detector) |

*(inference)* With a 720p webcam viewing a projected frame at half its width, one camera pixel is about two projector pixels, so expect 1–2 projector pixels residual before any refinement.

### Pattern choice

- **ArUco/ChArUco (OpenCV)**: single frame; low contrast is handled by adaptive thresholding (defaults `adaptiveThreshWinSizeMin/Max/Step = 3/23/10`, `adaptiveThreshConstant = 7`). Use `cornerRefinementMethod = CORNER_REFINE_SUBPIX` for sub-pixel corners. Markers must be big enough to decode; `minMarkerPerimeterRate` default 0.03 (relative to the largest image dimension). *(inference)* Marker sides of at least 25–30 camera pixels; project dark-on-light markers at full brightness, even if the UI is dark.
- **Gray code / binary-coded**: dense, ~10 images per axis for 1024 positions [1]; Moreno et al. recommend Gray code because it is "robust to decoding errors" and use fully-lit and fully-dark images for thresholding [39]. Needs the exposure locked and rolling-shutter banding handled; use average of several frames per pattern *(inference)*.
- **Chessboard**: simple and sub-pixel accurate but needs all corners visible and unlabelled; fine for planar `H` but no ID for partial views.
- **Camera intrinsics**: calibrate the webcam once with a printed ChArUco board (`cv2.calibrateCamera` from `matchImagePoints` output) and undistort before everything else *(inference)*. Moreno's result shows the projector also has distortion; with a homography-only model, that remains as residual.

### OpenCV 5.x `cv2.aruco` API (checked in `cv2` 5.1.0 and the 5.x headers [38])

Names that exist (checked by `hasattr` in 5.1.0): `ArucoDetector`, `DetectorParameters`, `RefineParameters`, `CharucoBoard`, `CharucoDetector`, `CharucoParameters`, `GridBoard`, `getPredefinedDictionary`, `generateImageMarker`, `drawDetectedMarkers`, `drawDetectedCornersCharuco`, `DICT_4X4_50 ... DICT_7X7_1000`, `DICT_ARUCO_ORIGINAL`, `DICT_APRILTAG_16h5/25h9/36h10/36h11`, `DICT_ARUCO_MIP_36h12`, `CORNER_REFINE_NONE/SUBPIX/CONTOUR/APRILTAG`.
Names that are **absent**: `estimatePoseBoard`, `drawMarker`, `interpolateCornersCharuco`, `DetectorParameters_create`, `Dictionary_get`, `CharucoBoard.create`.
Gotchas: `CharucoBoard(size, squareLength, markerLength, dictionary, ids=noArray())` takes `size = (squaresX, squaresY)`. The ChArUco pattern for even row counts changed incompatibly in 4.6.0; boards from calib.io use the *legacy* layout, set with `board.setLegacyPattern(True)`. A mismatch fails silently: markers detect, `detectBoard` returns zero ChArUco corners [38]. `detectBoard` returns `(charucoCorners, charucoIds, markerCorners, markerIds)` in Python.

Working snippet (ran in the repo's `.venv`: 27 markers, 40 corners, 0.40 px RMS on a synthetic render):

```python
import cv2, numpy as np
A = cv2.aruco
board = A.CharucoBoard((9, 6), 0.04, 0.03, A.getPredefinedDictionary(A.DICT_4X4_50))
canvas = board.generateImage((1080, 720), marginSize=20, borderBits=1)      # project this
det = A.CharucoDetector(board)                                              # detector params optional
ch_corners, ch_ids, m_corners, m_ids = det.detectBoard(gray_camera_frame)
obj, img = board.matchImagePoints(ch_corners, ch_ids)                       # obj (N,1,3) board plane, img (N,1,2)
H, inl = cv2.findHomography(obj.reshape(-1, 3)[:, :2], img.reshape(-1, 2), cv2.RANSAC, 2.0)
```

*Board units*: `obj` is in the board's own units; scale to projector pixels before building `H_proj→cam` *(inference)*.

### Detecting that something moved

- Sukthankar et al.: the projector shows calibration slides; "the system can also determine when the mapping is no longer accurate and trigger automatically recalibration as necessary" [40]. Detail not given.
- *(inference)* Camera moved: keep a few printed ArUco markers fixed on the wall *outside* the projected area; their pixel positions are a direct movement signal. Projector moved or re-keystoned: project a small marker set in the screen corners for one frame every few seconds (or when the predicted-vs-observed residual rises), and compare the detected corners with those predicted by the stored `H`. Trigger recalibration when RMS exceeds about 1.5× the calibration RMS for several consecutive checks. Thresholds are guesses to be tuned.

### References

37. S. Garrido-Jurado, R. Muñoz-Salinas, F. J. Madrid-Cuevas, M. J. Marín-Jiménez. *Automatic generation and detection of highly reliable fiducial markers under occlusion.* Pattern Recognition 47(6):2280–2292, 2014. doi:10.1016/j.patcog.2014.01.005 **[A]**
38. OpenCV 5.x headers: https://raw.githubusercontent.com/opencv/opencv/5.x/modules/objdetect/include/opencv2/objdetect/aruco_detector.hpp , `charuco_detector.hpp` , `aruco_board.hpp` , `aruco_dictionary.hpp` (same directory) **[R]**; names re-checked in installed `cv2` 5.1.0 **[R]**
39. D. Moreno, G. Taubin. *Simple, Accurate, and Robust Projector-Camera Calibration.* 3DIMPVT 2012, pp. 464–471. doi:10.1109/3DIMPVT.2012.77. http://mesh.brown.edu/calibration/ **[R]** (PDF from the project page)
40. R. Sukthankar, R. G. Stockton, M. D. Mullin. *Smarter Presentations: Exploiting Homography in Camera-Projector Systems.* ICCV 2001, pp. 247–253. https://www.cs.cmu.edu/~rahuls/pub/iccv2001-rahuls.pdf **[R]**
- Also used: [1], [2].

---

## 7. Automatic keystone correction with an uncalibrated camera

**Answer.** From the projector→camera homography alone you get the projected quadrilateral *as the camera sees it*, which is not a metric view of the wall. To make the picture truly rectangular you need **one metric reference**: (a) the screen's own rectangular frame, assumed rectangular, as in Sukthankar et al. [41]; (b) gravity (tilt sensors) plus a calibrated camera-projector pair as in Raskar and Beardsley [42]; (c) a printed marker of known shape on the wall *(inference)*; or (d) the **viewer-position assumption**, "the camera is a proxy for the viewer" [2], meaning the camera image is treated as the metric frame. Then find the largest axis-aligned rectangle of the wanted aspect inside the quadrilateral. This is a 3-variable linear program.

### Published procedures

- **Sukthankar et al. [41]** (steps from the paper): (1) uncalibrated camera, unknown poses; (2) projector shows a white slide, the screen quadrilateral is found in the camera image (assumes the screen is a uniformly light, rectangular object), giving mapping `C` up to scale; (3) `P = C^-1 T` where `T` is the projector-to-camera homography; (4) place the pre-warped image as "the largest rectangle with appropriate aspect ratio within the projected computer display"; the paper uses a "heuristic optimization" for the dimensions. Interactive corner refinement is offered, since `W` may be inaccurate. Needs the whole screen frame visible.
- **Raskar and Beardsley [42]**: calibrate camera and projector with ≥2 homographies on blank planes (projective, then Euclidean reconstruction, with a vertically offset projector principal point), triangulate the 4 corners of the illuminated quadrilateral, rotate into the world frame using two tilt sensors (gravity), then "compute the largest axis aligned rectangle inscribed in the projected quadrilateral on the plane and display strictly inside this rectangle" (4:3). Works on blank walls but needs the tilt sensor and a calibrated camera.
- General results: largest inscribed rectangles in convex sets and polygons: approximation schemes (Behroozi [43]) and exact algorithms for axis-aligned rectangles in convex polygons (Knauer et al. [44], abstract only).

### The maths for a fixed aspect ratio *(derivation; code tested locally)*

Work in a metric wall frame where the desired rectangle's sides are axis-aligned. Let the convex quadrilateral be `Q = { x : n_i · x ≤ c_i, i = 1..4 }`, the aspect ratio `a = W/H`. A rectangle with lower-left corner `(x, y)`, width `w`, height `h = w/a` lies in `Q` iff its four corners do (Q convex):

```
maximise  w
s.t.   n_i · (x + s_j w,  y + t_j w/a)  ≤  c_i      for i = 1..4, (s_j, t_j) ∈ {0,1}²
```

It is a linear program in `(x, y, w)` with 16 inequalities. Without SciPy, bisect on `w`: for a given `w` a rectangle fits iff the four copies of `Q` shifted by `−(corner offsets)` have a common point, which is a convex-polygon intersection (`cv2.intersectConvexConvex`). Rotation adds one parameter: scan `θ` over a small range in the rotated frame, or fix it to the wall's vertical (gravity, or the screen edge direction).

```python
import cv2, numpy as np

def largest_rect(quad, aspect):
    """Largest axis-aligned rect, width/height = aspect, inside convex quad (4x2, metric wall frame)."""
    q = np.asarray(quad, np.float32)
    def fit(w):
        h, inter = w / aspect, q
        for dx, dy in ((0, 0), (w, 0), (0, h), (w, h)):
            ok, inter = cv2.intersectConvexConvex(inter, q - np.float32([dx, dy]))
            if ok <= 0:
                return None
        return inter.reshape(-1, 2).mean(0)          # any point of the intersection = lower-left corner
    lo, hi, best = 0.0, float(np.ptp(q[:, 0])), fit(1e-3)
    for _ in range(40):
        mid = (lo + hi) / 2
        p = fit(mid)
        if p is None: hi = mid
        else: lo, best = mid, p
    return best[0], best[1], lo, lo / aspect          # x, y, w, h
```

Checks that passed locally (`.venv`, OpenCV 5.1, NumPy 2): a 100×100 square with 16:9 gives `w ≈ 100, h ≈ 56.25`; a keystoned trapezoid `(10,0),(90,0),(100,100),(0,100)` with 4:3 gives `x=6.52, y=34.78, w=86.96, h=65.22` with all corners inside.

Then the pre-warp is the homography mapping the source-image corners to this rectangle's corners expressed in projector pixels (via `H^-1` and the metric-frame homography), applied to what the engine sends to the projector. Keep the *same* rectangle as the coordinate frame for touch mapping; otherwise clicks land off by the pre-warp.

*(inference)* For this project the lowest-cost reference is (d) with the **near-projector camera** (so "viewer ≈ camera" is roughly true for the audience), or (c) one printed ArUco marker on the wall. The side phone is a poor viewer proxy.

### References

41. R. Sukthankar et al. (Carnegie Mellon). *Automatic Keystone Correction for Camera-assisted Presentation Interfaces.* The extracted text shows no author list or venue; authorship is inferred from the CMU listing and file name (`sukthankar_rahul_2000_1`); treat the year (2000) as unverified. https://ri.cmu.edu/pub_files/pub2/sukthankar_rahul_2000_1/sukthankar_rahul_2000_1.pdf **[R]**
42. R. Raskar, P. Beardsley. *A Self-Correcting Projector.* CVPR 2001. https://web.media.mit.edu/~raskar/Pocket/KeystoneCorrection/selfCorrectingProjector.pdf **[R]**
43. M. Behroozi. *Largest Inscribed Rectangles in Geometric Convex Sets.* arXiv:1905.13246. https://arxiv.org/abs/1905.13246 **[A]**
44. C. Knauer et al. *Largest Inscribed Rectangles in Convex Polygons.* J. Discrete Algorithms, 2012. https://algo.uni-rostock.de/storages/uni-rostock/Alle_IEF/Inf_ALGO/Publications/Knauer2012.pdf **[A]**
- Also used: [2].

---

## 8. Existing open-source projects and their problems

**Answer.** I found **no mature open-source project that does what VisionTouch plans** (predicted-image subtraction plus fingertip plus click/hover with a visible-light camera). The ones on GitHub are small (0–1 stars) and avoid the hard part: they run a hand model on the raw camera image, map with a four-corner homography, and decide "touch" by a button, a depth threshold, or by being inside the area. Treat this as a weak sample: I read four repositories and one academic system.

| Project | Approach | How touch is decided | Reported problems (verbatim where quoted) |
|---|---|---|---|
| `nonnopinto94/mat-touch` [45] (MIT, 10 commits) | Webcam + MediaPipe Pose/Hands + homography + One Euro filter; output as browser touch events via the Chrome DevTools Protocol | Point inside the calibrated area; frame-count debounce to enter/leave; `margin = 0.05` | "on a laptop i5-8250U with a 720p USB webcam, Pose runs at about 12 fps with about 100 ms of delay"; "built-in laptop webcams are often stuck at 7–8 fps"; "many webcams slow down in dim light because of auto exposure"; touches land wrong after the camera or projector is moved. Camera advice: "mount it right next to the projector lens, pointing the same way" |
| `ksafiul123/LuminaTouch` [46] (MIT, 3 commits) | Webcam + MediaPipe `hand_landmarker.task`, index fingertip to OS cursor, 4-click perspective transform, EMA + deadzone | A wireless presenter remote's *Down key* is the click, "eliminating depth ambiguity and false taps" | Windows only, needs admin for the keyboard hook; advises locking exposure and disabling autofocus "to prevent frame-rate drops during slide transitions"; recommends a 720p@60 camera |
| `Michdo93/interactive-projector` [47] (1 star) | Kinect v1/v2 depth, baseline of the empty surface, blob in a height band | Blob 5–25 mm above surface (v2) / 10–40 mm (v1); min height `max(TOUCH_MIN, 3.0 × noise)`; hold frames 2–3 | "Only one touch point"; "beyond ~1.8 m a finger on the table can hardly be separated from the surface"; v1 fingers cast IR shadows; Kinect v2 over USB/IP "drops out or causes extreme latency"; no Wayland |
| LighTouch (`LighTouchOrg`) [48] | Camera on top of the projection, Bluetooth clicks to the PC | "Smart camera detects touch points"; no detail given | Student project; its profile says the code is not public although a `Software` repo (C#, GPL-3.0) exists; I did not read it |
| Wiimote whiteboard, J. C. Lee [49] | Wii Remote IR camera + IR LED pen | Pen button lights the LED | From citing papers: the pen needs a button press; abstract of the cited article only [A]. IR, not visible light |
| PlayAnywhere [13] | IR + shadow analysis | see section 2 | Limits listed in section 2 |
| Sukthankar et al. [40] | Uncalibrated camera, laser pointer or finger tracking, homography | Pointer on virtual slide buttons | ±7 px base accuracy, ±3 px after temporal combination at 20 Hz on a 1024×768 slide with a low-resolution parallel-port camera |

Recurring user-visible issues, all from the table: **dim-room auto-exposure slows the camera**, **built-in webcams run at 7–15 fps**, **recalibration after any bump**, **single-point only**, and **latency around 100 ms**. Commercial products (interactive projectors with IR curtains, Xperia Touch, etc.) were not investigated.

### References

45. https://github.com/nonnopinto94/mat-touch **[R]** (README)
46. https://github.com/ksafiul123/LuminaTouch **[R]** (README + empty issue list)
47. https://github.com/Michdo93/interactive-projector **[R]** (README)
48. https://github.com/LighTouchOrg **[R]** (organisation profile only)
49. J. C. Lee. *Hacking the Nintendo Wii Remote.* IEEE Pervasive Computing 7(3):39–45, 2008. doi:10.1109/MPRV.2008.53. https://www.researchgate.net/publication/3437335_Hacking_the_Nintendo_Wii_Remote **[A]**
- Also used: [13], [40].

---

## 9. Latency

**Answer.** Perception studies put the target at **under about 40 ms for direct touch** and **under 75 ms for indirect**, with benefit continuing below 10 ms [51][52][53]. A webcam pipeline sits far above that: camera sampling delay alone is up to one frame period (about 50 ms mean at 25 Hz in a measurement study [56]), consumer webcams reach 50–200 ms end to end [U], and mat-touch measured about 100 ms [45]. So VisionTouch should **hide** latency (instant local feedback, hysteresis on clicks), **filter** with the One Euro filter [54], and **reduce** work (small processing resolution). Prediction helps only for short horizons.

### What matters to a user

- Jota et al. [51]: tested 1, 10, 25, 50 ms of added cursor latency on dragging. No significant throughput difference between 1 and 10 ms; every larger step degraded performance; commercial touchscreens show 50–125 ms; the paper cites a perceptual floor "somewhere between 2–11 ms".
- Ng et al. [52]: abstract (as shown by the ACM listing, not read in full): typical systems take 50–200 ms; "users greatly prefer lower latencies, and noticeable improvement continued well below 10 ms"; proposes immediate low-fidelity feedback followed by normal-latency rendering.
- Deber et al. [53]: dragging JND 11 ms (direct) and 55 ms (indirect); tapping 69 ms and 96 ms; design targets below 40 ms (direct) and 75 ms (indirect). These numbers come from a secondary summary of the paper, not the paper text [A].
- *(inference)* Which bound applies: projected touch is *direct* manipulation on the surface, but the cursor is rendered by a loop that is 100+ ms behind the finger, so users see a trailing cursor. The cheapest mitigation is local feedback (a ring under the fingertip drawn at the detected position) combined with a click rule that does not need frame-precise timing.

### What the pipeline costs (measured or stated)

| Stage | Number | Source |
|---|---|---|
| Camera sampling + glass-to-glass at 25 Hz (min/mean/max) | 24.8 / 50.4 / 78.7 ms | [56] |
| Same at 300 Hz | 8.1 / 15.5 / 23 ms | [56] |
| USB webcam, optimised capture settings (stopwatch method) | 176.67 ms | IEEE 9339646 **[A]** |
| Pose-based tracker on i5-8250U, 720p USB webcam | ≈12 fps, ≈100 ms | [45] |
| MediaPipe HandLandmarker (full), Pixel 6 | 17.12 ms CPU, 12.27 ms GPU | [31] |
| scrcpy display mirroring (claim in the project's README) | 35–70 ms | [28] |
| Subtraction at reduced resolution | 2.3 ms vs 29.6 ms for saliency pipeline (2.8 GHz CPU, 2012) | [6] |

[4] kept latency low by estimating the image at 320×240 regions instead of projector resolution.

### Filtering and prediction

**One Euro filter** [54] (equations confirmed from the authors' Python source and the paper text):

```
τ = 1 / (2π f_c)           α = 1 / (1 + τ / T_e)         T_e = sampling period (1/rate)
dx̂ = lowpass(dx,  α(f_cd))  with  f_cd = 1 Hz default     dx = (x − x̂_prev) / T_e
f_c = f_cmin + β · |dx̂|
x̂ = α(f_c) · x + (1 − α(f_c)) · x̂_prev
```

Tuning (authors' page [54]): set `β = 0`, `f_cmin = 1 Hz`; hold still or move slowly and lower `f_cmin` until jitter is gone; then move fast and raise `β` until lag disappears (start near 0.001 / 0.0001 and scale by 10). Lower `f_cmin` means less jitter, more lag. `β` depends on the units of your signal. The paper's CHI example settles at `f_cmin = 1 Hz`, `β = 0.007`; the repo's README example uses `freq 120, mincutoff 1.0, beta 0.1` (different units, so do not copy). Python package: `pip install OneEuroFilter`; `OneEuroFilter(freq, mincutoff=1.0, beta=0.0, dcutoff=1.0)`, call `f(x, timestamp)`; scalar only, so use one instance per axis. **Gotcha in the source**: the rate update tests `if self.__lasttime and timestamp and timestamp > self.__lasttime`, so a timestamp of `0` is falsy and the rate is not updated; start timestamps above 0. Pass the *capture* timestamp, not the loop time.

**Prediction**: LaViola's double exponential smoothing predicts by extrapolating a linear trend; reported to match Kalman and extended-Kalman predictors for head and hand tracking while running about 135× faster [55] (abstract only). A third-party multi-touch pipeline notes it assumes near-linear motion, valid only over short horizons, and equally spaced samples [A]. For a fingertip tracked at 30 fps with 100+ ms of delay, extrapolation by 100 ms will overshoot on stops; use it for the *hover ring* only, never for the click position *(inference)*.

**Timestamp alignment between screen capture and camera** *(no primary source found; design suggestion)*:
1. Keep a ring buffer of the last N captured screen frames, each with a monotonic timestamp taken when `mss` returns.
2. Estimate the fixed offset Δ once: project a patch that alternates black/white at a known frame index (or a binary counter) and cross-correlate its camera brightness with the logged screen timestamps; this is the same idea as the LED-and-photodiode and stopwatch delay measurements in [56].
3. At each camera frame at time `t`, build the predicted image from the screen frame closest to `t − Δ`, not the newest one. Without this, every fast content change produces a ghost foreground.

### References

51. A. Jota, A. Ng, P. Dietz, D. Wigdor. *How Fast is Fast Enough? A Study of the Effects of Latency in Direct-Touch Pointing Tasks.* CHI 2013, pp. 2291–2300. https://www.tactuallabs.com/papers/howFastIsFastEnoughCHI13.pdf **[R]**
52. A. Ng, J. Lepinski, D. Wigdor, S. Sanders, P. Dietz. *Designing for Low-Latency Direct-Touch Input.* UIST 2012, pp. 453–464. doi:10.1145/2380116.2380174. https://doi.org/10.1145/2380116.2380174 **[A]**
53. D. Deber, R. Jota, C. Forlines, D. Wigdor. *How Much Faster is Fast Enough? User Perception of Latency & Latency Improvements in Direct and Indirect Touch.* CHI 2015, pp. 1827–1836. doi:10.1145/2702123.2702300. https://www.tactuallabs.com/papers/howMuchFasterIsFastEnoughCHI15.pdf **[A]**
54. G. Casiez, N. Roussel, D. Vogel. *1 € Filter: A Simple Speed-Based Low-Pass Filter for Noisy Input in Interactive Systems.* CHI 2012, pp. 2527–2530. doi:10.1145/2207676.2208639. https://direction.bordeaux.inria.fr/~roussel/publications/2012-CHI-one-euro-filter.pdf ; project page and code https://gery.casiez.net/1euro/ , https://github.com/casiez/OneEuroFilter **[R]**
55. J. J. LaViola. *Double Exponential Smoothing: An Alternative to Kalman Filter-Based Predictive Tracking.* IPT/EGVE 2003. https://cs.brown.edu/people/jlaviola/pubs/kfvsexp_final_laviola.pdf **[A]**
56. C. Bachhuber, E. Steinbach. *A System for High Precision Glass-to-Glass Delay Measurements in Video Communication.* arXiv:1510.01134 (ICIP 2016, venue from memory, unverified). https://arxiv.org/abs/1510.01134 **[R]**
- Also used: [4], [6], [28], [31], [45].

---

## Appendix: facts that conflict or could not be verified

- **scrcpy version**: the brief says 4.x; the releases page shows 5.0.1 as latest (years inferred).
- **mediapipe `mp.solutions`**: GitHub master still has `solutions/hands.py`, but the 1.2.3 wheel in `.venv` has no `mp.solutions` (checked by import).
- **AVFoundation unsupported-property return value**: 0 in the 4.x source I read; −1 per the 5.0 migration note. Not re-verified in 5.x `getProperty`.
- **Apple-silicon built-in camera exposure lock**: unverified; needs a runtime probe.
- **uvc-util on Apple silicon**: no issue or documentation either way; not run.
- **DLP colour-wheel speeds** other than the 120 Hz in [18]: no vendor document obtained.
- **ACM papers** [52][53]: only abstracts and secondary summaries; numbers from [53] need a check against the PDF.
- Items tagged *(inference)* throughout, especially the ratio test, per-row gain correction, shadow geometry `d = h·tan α`, the timestamp-alignment procedure, and all numeric thresholds in section 6.
