# UX guidelines

Two briefs from the product owner. They are the reference for every frontend change. Read both before redesigning or adding controls.

## Brief 1: Touch-first interaction / iPhone UX

This application must be designed touch-first.

A primary use case is someone holding an iPhone in one hand while speaking, listening or reading. The interface must therefore be extremely easy and forgiving to operate with a thumb.

Do NOT optimize primarily for mouse precision and then make the layout responsive. Design the mobile interaction first.

### Touch targets

There must be no tiny or fiddly interactive elements.

- Every important action needs a generous touch target.
- Aim for at least 44x44 CSS px for interactive controls.
- Frequently used controls should usually be larger than the minimum.
- An icon may visually be small, but its tappable area must remain large.
- Leave sufficient spacing between neighboring actions to prevent accidental taps.
- Never require the user to precisely hit a tiny icon, chevron, label or waveform.
- Do not create dense rows of miniature icon buttons just because they look elegant.

Especially review: language switching, play / pause, mute, audio/text mode switching, transcript visibility, text-size controls, microphone controls, sharing/invite controls. All of these must be comfortably usable with a thumb.

### One-handed operation

Design important mobile interactions around the natural thumb zone. Frequently used controls should preferably live in the lower or middle part of the viewport instead of requiring the user to reach to the top of the phone. Avoid putting essential session controls into tiny buttons in the top corners.

Consider a contextual bottom control area for the listener, for example `Audio + Text | Audio | Text`. The implementation does not have to follow this exact layout. The goal is that switching between listening and reading takes one obvious tap.

### Progressive disclosure

Do not permanently display every possible setting. The main screen should contain only the controls required during normal use. Less frequently used settings can appear through bottom sheets, popovers, contextual menus or expandable controls. On mobile, prefer a well-designed bottom sheet over tiny dropdown menus. For example, tapping the language pair could open a large touch-friendly language selector instead of permanently showing multiple small selectors.

### Gestures

Gestures may enhance the interface, but must never be the only way to perform an important action. Every important gesture must have an obvious tappable alternative. Do not invent gestures simply to make the interface feel novel.

### Listener UX

The listener should be able to change their consumption mode almost instantly and without navigating through settings. The three conceptual modes are `Listen + Read`, `Listen`, `Read`. Optimize these transitions for one-handed use.

Listen mode: one tap should be enough to hide the transcript. The resulting screen should become calmer rather than leaving an empty transcript area behind. Audio controls should become larger and easier to operate.

Read mode: one tap should transform the interface into a reading-focused experience. The translated text should use most of the available viewport. Text-size adjustment must be extremely easy. Do NOT implement three tiny A-/A/A+ buttons. Consider a larger control, bottom sheet, segmented size selector or another touch-friendly interaction. The user should be able to reach `Normal`, `Large`, `Extra Large` without precision tapping. Changing text size should immediately reflow the interface. Provide a distraction-free reading mode where almost all UI can disappear except live state, language, translated text and one obvious way to restore controls.

### Interaction feedback

Every tap should feel immediate. Use subtle tactile-feeling visual feedback: pressed states, short transitions, clear selected states, immediate mode changes. Avoid animations that delay the actual interaction. The UI should never leave the user wondering whether a tap was registered. Where appropriate, use native mobile interaction conventions instead of inventing custom controls.

### Mobile viewport

Use the available iPhone screen efficiently. Account for safe-area-inset-top, safe-area-inset-bottom, dynamic browser chrome, 100dvh / dynamic viewport behavior and landscape orientation. Avoid long vertically stacked layouts. The user should not need to scroll through the application just to reach primary controls. During an active session, the interface should behave more like a native mobile application than a responsive website.

### UX test

After implementing a redesign, explicitly perform a "thumb test". Review every interactive element at approximately iPhone viewport sizes and ask:

1. Can I confidently tap this while holding the phone in one hand?
2. Is the target large enough without precision?
3. Is there enough distance from neighboring actions?
4. Can I understand what will happen before tapping?
5. Can I undo or change the action easily?
6. Do I need to scroll unnecessarily?
7. Is an important action hidden behind an unnecessarily small icon?
8. Could this control be simpler?

If any primary interaction feels fiddly, redesign it. The target experience: "Someone receives a link, opens it on an iPhone and understands how to listen or read the translation within a few seconds without instructions."

## Brief 2: Product identity, away from the generic AI/SaaS look

The primary goal is NOT to make it "more beautiful" or "more premium". The goal is to remove the generic AI-generated / SaaS-template feeling and give Translate Live its own recognizable product identity. Do not just change colors, border radii or spacing. Question the visual hierarchy, layout, interaction model and component structure.

### Product context

Speaker: speaks naturally into a microphone, sees the live transcript, chooses spoken and translated language, can invite listeners. Listener: joins through a link, can listen to translated audio, read the translated live transcript, use both together, or consume ONLY audio or ONLY text. The UI should feel like a purpose-built live communication product rather than an AI chatbot or generic dashboard.

### Patterns to remove

Oversized marketing hero headline inside the application, excessive centered alignment, everything inside rounded cards or pills, too many similar dark grey surfaces, generic glassmorphism, glowing circular AI/orb visualization, excessive empty vertical space, repetitive 1px borders, weak distinction between important controls and decorative elements, generic "premium dark SaaS" visual language, translation not feeling like the core of the product, speaker/listener modes without distinct interaction patterns, landing page mixed with application. Do NOT solve this by adding gradients, blobs, glowing borders, floating cards or decorative AI animations.

### Direction

Treat Translate Live like a combination of live captions, an interpreter console, a beautifully designed audio player and an editorial reading experience. Not like ChatGPT, an AI assistant, a SaaS dashboard, a crypto app or a generic Tailwind landing page. The translation and the human voices are the visual protagonists.

Prefer strong typography, intentional whitespace, clear hierarchy, asymmetric layouts where appropriate, fewer containers, fewer borders, fewer pills, flat surfaces when a card is unnecessary, subtle depth instead of universal glassmorphism, excellent typography for live text, meaningful micro-interactions, controls that visibly relate to live translation/audio. Do not wrap every section in a card.

### Speaker view

Most important elements in order: session state, source → target language, microphone / speaking state, live transcript, listener sharing. The language pair should be recognizable at a glance without looking like two form inputs, for example a compact route `Deutsch → English` with switching through interaction. The microphone should feel like a live broadcast control rather than an AI orb; use actual microphone amplitude or a subtle waveform instead of a fake animation. Paused / Live / Listening / Connecting must be clearly identifiable states. Avoid a giant circular glowing button.

### Listener view

Three explicit consumption modes `Audio + Text`, `Audio`, `Text`, easy to switch while the session runs. Audio + Text: compact audio controls and live text together. Audio: transcript hidden completely, audio controls dominant, session/language context without unnecessary UI, no empty transcript container, almost like a live radio/interpreter stream. Text: a dedicated reading experience where the text becomes the main interface, with simple text-size controls up to a large presentation/accessibility mode. Large-text mode recomposes the screen around the text instead of enlarging a card. The listener can hide almost everything except the live translation.

### Transcript design

Not another card. Editorial / caption-oriented: current sentence large and high contrast, previous sentences smaller and reduced contrast, incoming text with a subtle transition. No chat bubbles. Keep the newest phrase visually anchored while older content flows above it. Source language is secondary metadata. Extremely readable on phones, tablets, desktops and presentation displays.

### Product identity

One small recognizable motif related to language, voice, translation or live communication. No sparkles, AI stars, robots, glowing brains, gradient blobs. Candidates: two typographic language lanes converging, a moving baseline representing speech, a translation direction line integrated into typography, a live waveform as structural element, deliberately different weights for source and translation, a tiny live pulse system. Choose ONE and use it consistently.

### Techniques

Container queries, clamp() typography, custom properties, color-mix(), dvh/svh, View Transitions API for mode switching, subtle masking, variable-font axes, Web Audio API for real visualization, prefers-reduced-motion, native popovers where appropriate. Animations communicate state changes only, with graceful fallbacks.

### Mobile, accessibility, copy

Mobile Safari is a primary target; the screen must not be a stacked landing page. On mobile the user should immediately understand what language is spoken, what they receive, whether the session is live and whether they are listening or reading. Accessibility: scalable transcript, strong contrast, clear focus states, keyboard navigation, screen-reader labels, reduced motion, touch targets, usable at 200 % zoom; text-only mode is an accessibility feature. Copy: short, human, functional; no marketing headline during a session; avoid phrases like seamless, effortlessly, intelligent, powered by AI, experience the future, break language barriers.

### Final check

"If the logo were removed, could this easily be mistaken for one of thousands of AI-generated dark SaaS templates?" If yes, keep refining. The result should feel purpose-built, calm, human, live, typographic and unmistakably related to translation and listening.
