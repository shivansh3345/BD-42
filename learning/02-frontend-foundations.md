# BD-42 — Walkthrough 02: Frontend Foundations

A guided tour of the React + Vite + Tailwind frontend we just built. Pitched
at "experienced JavaScript developer who knows Angular and is new to React."
Where useful, I draw the Angular comparison directly — most React confusions
for an Angular dev come from expecting the same patterns to apply, and they
mostly don't.

Same template as `01-foundations.md`. Each stop has:

- **The question** the stop answers
- **The plain-language story**
- **Code references** so you can follow along
- **The key insight** in one sentence
- **What to call it** when explaining to someone else (or in an interview)

---

## The map

| Stop | The question                                                          | The concept                            |
|-----:|-----------------------------------------------------------------------|----------------------------------------|
|    1 | What happens between pressing Send and the reply showing up?          | The frontend request lifecycle         |
|    2 | Where does state live in a React app?                                 | `useState`                             |
|    3 | How does code run "in response to" something changing?                | `useEffect`                            |
|    4 | Why does `sessionId` live in `App`, not in `ChatPanel`?               | Lifting state up; props down, events up |
|    5 | Why is the input value bound through state instead of directly?       | Controlled inputs / one-way data flow  |
|    6 | What's the `cancelled` flag doing in `FactsPanel`?                    | Effect cleanup + async race conditions |
|    7 | What's actually going on inside JSX?                                  | Conditional render, list keys, fragments |
|    8 | What are all those Tailwind classes?                                  | Utility-first CSS                       |
|    9 | Modern JS idioms we leaned on                                         | Spread, optional chaining, async/await, `crypto.randomUUID`, etc. |

---

## Stop 1 — What happens when you press Send

> **The question:** You type a message, press Enter. What runs, in what order,
> until BD-42's reply lands in the bubble above?

### The story

Trace one round trip:

1. The textarea has its `value` bound to React state called `input`. As you
   type, every keystroke fires `onChange`, which calls `setInput(e.target.value)`,
   which schedules a re-render with the new value showing.
2. You press Enter. The `onKeyDown` handler fires. It checks `e.key === 'Enter'`
   and `!e.shiftKey` (so Shift+Enter still inserts a newline), calls
   `e.preventDefault()` to stop the browser from inserting a newline, and
   invokes `sendMessage(input)`.
3. `sendMessage` builds a `{role: 'user', content: trimmed}` object, appends
   it to `messages` state (so the user's bubble appears immediately, before
   we've heard from the server), clears the input, and sets `isLoading` to
   `true`.
4. We `await fetch('http://localhost:8000/chat', { ... })`. This is a
   network round trip. While it's in flight, the component is showing the
   user bubble + the loading dots (because `isLoading === true`).
5. The response comes back as JSON: `{reply, fact_captured}`. We append a
   new `{role: 'assistant', content: data.reply, fact: data.fact_captured}`
   to messages and flip `isLoading` back to `false`.
6. We call `onChatComplete()` — a callback prop from `App` — which
   increments `factsRefreshKey`. That change cascades into `FactsPanel`'s
   effect dependency array, triggering a re-fetch of `/facts/{sessionId}`.
7. Each time `messages` or `isLoading` changes, a separate `useEffect`
   smooth-scrolls the messages container to its `scrollHeight` so the new
   bubble is in view.

### Visual

```
   User presses Enter
        │
        ▼
   handleKeyDown → sendMessage(text)
        │
        ▼
   ┌──────────────────────────────┐
   │ optimistic update            │
   │   setMessages([...prev, u])  │ ← user bubble appears IMMEDIATELY
   │   setInput('')               │
   │   setIsLoading(true)         │ ← loading dots appear
   └──────────┬───────────────────┘
              │
              ▼
   ┌──────────────────────────────┐
   │ await fetch('/chat', ...)    │ ← HTTP call to FastAPI
   └──────────┬───────────────────┘
              │
              ▼
   ┌──────────────────────────────┐
   │ on success:                  │
   │   setMessages([...prev, a])  │ ← assistant bubble appears
   │   setIsLoading(false)        │
   │   onChatComplete()           │ ── bumps refreshKey in App ──┐
   └──────────────────────────────┘                              │
                                                                  ▼
                                                       FactsPanel re-fetches
                                                       (its useEffect sees the
                                                       new refreshKey)
```

### Code references

- The whole flow: `web/src/components/ChatPanel.jsx` — `sendMessage`
  function near the top of the component
- Auto-scroll effect: same file, the first `useEffect`
- Refresh-key cascade: `web/src/App.jsx` — `handleChatComplete` +
  `<FactsPanel refreshKey={factsRefreshKey} />`

### Key insight

> **The user's bubble appears before the server responds.** That's an
> intentional UX choice called **optimistic UI** — you update local state
> immediately as if the action succeeded, then reconcile when the real
> response arrives. It's why the chat feels snappy even on slow networks.

### Name this

- **Optimistic update / optimistic UI**
- **Round trip** — the request-out, response-back cycle

---

## Stop 2 — `useState`: where state lives

> **The question:** In Angular, component state lives on `this`. In React,
> components are *functions*, not classes. Where does the state go?

### The story

In Angular:

```typescript
@Component({...})
export class ChatComponent {
  input = '';
  messages: Message[] = [];
}
```

You attach state to `this`. The template binds to `input` directly. When
`input` changes, Angular's change detection re-renders the component.

In React with hooks, the component is a function that runs *every time it
re-renders*. So a local variable like `let input = ''` would reset on every
render — totally useless. We need a way to persist state *across renders* and
trigger a re-render when it changes. That's `useState`:

```jsx
const [input, setInput] = useState('')
```

Translation: "Give me a piece of state called `input`, initialized to `''`,
and a function `setInput` I can call to change it. When I call `setInput`,
re-run this component function and reflect the new value in the UI."

A few things to internalize:

- `useState` returns a **two-element array**, destructured as
  `[value, setterFunction]`. The names are yours to pick.
- You **never mutate** state directly. `messages.push(newMsg)` will not
  trigger a re-render. `setMessages(prev => [...prev, newMsg])` does.
- Each call to `setX` schedules a re-render. React batches them so multiple
  state changes in the same event handler usually result in a single render.

### Code references

- All four piece of `ChatPanel` state: `web/src/components/ChatPanel.jsx`,
  top of the component — `messages`, `input`, `isLoading`, `error`
- `App` state: `web/src/App.jsx`, top of the component — `sessionId`,
  `factsOpen`, `factsRefreshKey`

### The functional-update pattern

When the new state depends on the old state, pass a **function** to the
setter:

```jsx
setMessages(prev => [...prev, newMsg])
//          ^^^^                       receives current value of messages
```

vs. the wrong-looking but tempting:

```jsx
setMessages([...messages, newMsg])
//                ^^^^^^^^         closure over a snapshot of `messages`
```

In simple cases both work. But if two state updates happen in quick succession
(say, two fact-capture pushes in the same tick), the snapshot version uses a
stale value and you lose one update. The functional version always sees the
freshest state. **Default to it.**

### Key insight

> **The component function re-runs on every render. State persists across
> those runs only because React stores it for you behind the scenes.** Hooks
> are the API for accessing that stored state.

### Name this

- **Hook** — any function whose name starts with `use`. They tap into
  React's internal state machinery.
- **Setter function** — the second element returned from `useState`.
- **Functional update** — passing `prev => next` to a setter instead of a
  value.

---

## Stop 3 — `useEffect`: code that runs *because* state changed

> **The question:** Sometimes you need to do something *when* state changes —
> fetch new data, scroll a container, set up a timer. Where does that code
> live?

### The story

In Angular, you'd use lifecycle hooks: `ngOnInit` for "on mount,"
`ngOnChanges` for "on prop change," `ngOnDestroy` for "on unmount." Or you'd
subscribe to Observables to react to streams.

React collapses all of that into one hook: `useEffect`.

```jsx
useEffect(() => {
  // do something
}, [someValue])
```

Read this as: **"after every render where `someValue` has changed, run this
function."** The array at the end is the **dependency array**. If it's empty,
the effect runs once after the first render (like `ngOnInit`). If you list
values in it, the effect runs whenever any of those values changes.

In `ChatPanel`:

```jsx
// Effect 1: auto-scroll whenever messages or loading state change
useEffect(() => {
  scrollRef.current?.scrollTo({
    top: scrollRef.current.scrollHeight,
    behavior: 'smooth',
  })
}, [messages, isLoading])

// Effect 2: when sessionId changes (e.g. user clicked "New session"),
// wipe the local message list and clear errors
useEffect(() => {
  setMessages([])
  setError(null)
}, [sessionId])
```

In `FactsPanel`:

```jsx
// Re-fetch facts whenever sessionId or refreshKey changes
useEffect(() => {
  // ...fetch...
}, [sessionId, refreshKey])
```

### Why "after render" matters

Effects run **after** React has committed the new DOM. That ordering is what
makes the auto-scroll work: by the time the effect runs, the new message
bubble is already in the DOM, so `scrollHeight` reflects the real new height.
If this code ran *during* render, `scrollHeight` would still be the old value.

### The three things effects are used for

1. **Synchronizing with external systems** — fetch data, subscribe to a
   WebSocket, set up a timer.
2. **Imperatively touching the DOM** — scroll, focus, measure.
3. **Reacting to prop/state changes** — like "when sessionId changed, clear
   the local message history."

Things effects are **not** for: deriving values from props/state. If you find
yourself doing `useEffect(() => { setX(y * 2) }, [y])`, just compute `x = y *
2` during render. Effects are an escape hatch, not the default.

### Key insight

> **`useEffect` is your escape hatch from React's pure-function model into
> the messy real world** (network, DOM, timers). The dependency array tells
> React *when* to re-run that code.

### Name this

- **Effect** — the code passed to `useEffect`.
- **Dependency array** — the second argument to `useEffect`.
- **Side effect** — anything a function does besides return a value (network
  call, DOM mutation, console log). Effects are where side effects go.

---

## Stop 4 — Lifting state up: why `sessionId` lives in `App`

> **The question:** `ChatPanel` sends messages. `FactsPanel` shows facts.
> Both need to know the `sessionId`. Where should it live?

### The story

Three options:

1. **In `ChatPanel`** — but then `FactsPanel` can't see it.
2. **In `FactsPanel`** — but then `ChatPanel` can't see it.
3. **In their common parent, `App`** — and pass it down to both as a prop. ✓

This is **lifting state up**, the most important data-flow rule in React.
The rule: state lives in the **lowest common ancestor** of the components
that need to read or write it.

In Angular, you might reach for a `Service` here (`@Injectable()` shared
state). React doesn't have services as a baseline — its preferred answer is
"lift the state until it's above everyone who needs it."

### Props down, events up

Look at `web/src/App.jsx`:

```jsx
<ChatPanel
  sessionId={sessionId}              // prop down: child reads
  onChatComplete={handleChatComplete} // callback prop: child triggers parent
  onReset={handleNewSession}          // callback prop
  onToggleFacts={() => setFactsOpen(v => !v)}
  factsOpen={factsOpen}
/>

<FactsPanel
  sessionId={sessionId}      // prop down
  refreshKey={factsRefreshKey}
  onClose={() => setFactsOpen(false)}
/>
```

`sessionId` and `factsOpen` are **data flowing down** from `App` to its
children. `onChatComplete`, `onReset`, `onClose` are **callbacks flowing
down so events can flow up**. The child doesn't mutate the parent's state
directly (it can't — state is private to the component that owns it). It
calls the callback, and the parent decides what to do.

Angular analogue: `@Input` for props, `@Output` events with `EventEmitter`
for the callbacks. Same pattern, different syntax.

### The refresh-key trick

A subtle thing in `App.jsx`: there's a state called `factsRefreshKey`. We
pass it to `FactsPanel` as a prop, but `FactsPanel` doesn't *use* the value
— it just lists it in its `useEffect` dependency array. So whenever `App`
calls `setFactsRefreshKey(k => k + 1)`, the prop change cascades into
`FactsPanel`'s effect, which triggers a re-fetch.

This is the **refresh key / version counter** pattern. It's how you say
"please re-run that effect" from outside the component, without exposing
imperative methods.

### Key insight

> **State lives at the lowest common ancestor of everyone who reads it.
> Children get data via props, send signals via callback props.** This is
> "props down, events up" — the React data-flow rule.

### Name this

- **Lifting state up**
- **Props** (data flowing from parent to child)
- **Callback prop** (a function passed as a prop so the child can signal up)
- **Controlled child** (one whose behavior is fully driven by props from the parent)
- **Refresh key / version counter** (the pattern of bumping a number to retrigger an effect)

---

## Stop 5 — Controlled inputs: why no `[(ngModel)]`?

> **The question:** In Angular you write `<input [(ngModel)]="input">` and
> the textbox value and the variable stay magically in sync. In React, why
> are we writing `value={input}` AND `onChange={(e) => setInput(...)}` ?
> That's two things for one job.

### The story

In Angular's two-way binding, the DOM input element holds the "real" value
and the framework reflects it back into your variable through some magic.

React refuses to do this. Its philosophy: **state is the single source of
truth, period.** The input is just a view onto state. You ask it to display
the current state via `value`, and you listen for change events via
`onChange` and update state yourself.

This is called a **controlled input**:

```jsx
<textarea
  value={input}                                    // display the state
  onChange={(e) => setInput(e.target.value)}       // when user types, update state
/>
```

The flow: user types → browser fires `change` event → handler reads
`e.target.value` → handler calls `setInput` → React re-renders → input
displays the new value.

### Why React chose this

Two-way binding is convenient but fragile. With it:

- You can't easily transform input as it's typed (lowercase it, strip
  non-numeric characters, limit length) without ugly workarounds.
- You can't easily prevent invalid input.
- Multiple inputs binding to the same value can drift out of sync.

With controlled inputs, every keystroke routes through your code. You're in
total control:

```jsx
onChange={(e) => setInput(e.target.value.toUpperCase())}   // shout mode
onChange={(e) => setInput(e.target.value.replace(/\d/g, ''))} // no digits
onChange={(e) => setInput(e.target.value.slice(0, 100))}    // length cap
```

### `e.preventDefault()` and form submission

There's a related pattern in `ChatPanel`'s `handleSubmit`:

```jsx
function handleSubmit(e) {
  e.preventDefault()   // ← stop the browser from reloading the page
  sendMessage(input)
}
```

Wrapping the composer in `<form onSubmit={handleSubmit}>` is intentional:
the browser will treat Enter-key submission semantically as a form submit,
which is good for accessibility (screen readers, autofill, etc.). But the
*default* browser behavior on form submit is to navigate to the form's
`action` URL and reload the page. Hence `preventDefault()`.

### Key insight

> **In React, the DOM displays your state — it never holds state of its
> own.** Controlled inputs make state the single source of truth, which
> trades a tiny amount of boilerplate for total predictability.

### Name this

- **Controlled input** — value comes from state, changes go through state.
- **One-way data flow** — state → DOM, not DOM ↔ state.
- **Synthetic event** — React wraps native DOM events in `e` so they behave
  consistently across browsers.

---

## Stop 6 — The `cancelled` flag: async + cleanup

> **The question:** In `FactsPanel.jsx`, why does the fetching effect look
> like this — with that weird `cancelled` variable?

```jsx
useEffect(() => {
  let cancelled = false
  async function fetchFacts() { /* ... */
    if (!cancelled) setFacts(data.facts || [])
  }
  fetchFacts()
  return () => { cancelled = true }
}, [sessionId, refreshKey])
```

### The story

Imagine the user clicks "New session" twice in rapid succession. Each click:

1. Changes `sessionId` (or `refreshKey` after a chat completes).
2. Re-runs the effect, which kicks off a `fetch()` for the new session.

Now suppose the second click happens *while the first fetch is still
in-flight.* What happens?

Without the cleanup:

```
t=0   Click 1 → fetch(session-A)  (still loading...)
t=1   Click 2 → fetch(session-B)  (still loading...)
t=2   session-A response arrives  → setFacts(A_data)      ← STALE DATA SHOWN
t=3   session-B response arrives  → setFacts(B_data)      ← correct
```

Between t=2 and t=3 (could be hundreds of ms), the user briefly sees the
wrong session's facts. Even worse, if session-A is slower, you might end up
*ending* on session-A's data, and the user sees totally wrong facts until
something else triggers a refetch.

### The fix

Every time the effect runs, it captures a fresh `cancelled` variable in its
closure. When that effect tears down (either because dependencies changed
*or* because the component unmounted), the **cleanup function** runs and
sets `cancelled = true`. The async work inside the *old* effect checks this
flag before calling `setFacts`. If the old request comes back after a new
one started, it sees `cancelled === true` and skips the state update.

```
t=0   Effect 1 starts, fetch-A in flight, cancelled1 = false
t=1   Effect 1 tears down (cleanup runs), cancelled1 = true
      Effect 2 starts, fetch-B in flight, cancelled2 = false
t=2   fetch-A returns → checks cancelled1 → TRUE → skip
t=3   fetch-B returns → checks cancelled2 → false → setFacts(B_data) ✓
```

### Name this

- **Cleanup function** — the function returned from a `useEffect`.
- **Race condition** — when the outcome depends on the timing of concurrent
  operations.
- **Stale closure** — a function that captures an outdated value because
  the surrounding state changed since the function was created. The
  `cancelled` flag is how we *detect* a stale closure and bail out.

### Key insight

> **Async effects + dependency changes = race conditions, by default. The
> cleanup function is React's hook for canceling stale in-flight work
> before its result gets a chance to corrupt newer state.**

You'll see two flavors of this pattern in the wild:

1. The boolean flag (what we used). Simple, works for any async work.
2. The `AbortController` (web platform native). Cleaner because you can
   actually cancel the network request, not just ignore its result.
   `fetch(url, { signal: controller.signal })`. Use this for production
   code; the boolean flag is fine for a demo.

---

## Stop 7 — JSX: the parts that look weird

> **The question:** What's actually happening with `{}`s in JSX,
> `messages.map(...)`, `&&`, ternaries, fragments?

### The story

JSX is sugar for `React.createElement()` calls. Anything between `{` and `}`
inside JSX is a **JavaScript expression** — the result of the expression is
rendered.

### Conditional rendering with `&&`

```jsx
{messages.length === 0 && !isLoading ? (
  <EmptyState />
) : (
  <div>...messages...</div>
)}
```

Two patterns combined:

- **Ternary** `cond ? A : B` — render A or B based on cond.
- **Short-circuit `&&`** — `cond && <X />` renders X only when cond is
  truthy. Gotcha: `0 && <X />` renders the literal `0` because `0` is
  falsy in a boolean sense but is also a "renderable" value. Avoid this
  by writing `cond > 0 && <X />` or `!!cond && <X />`.

### List rendering with `.map`

```jsx
{messages.map((m, i) => (
  <div key={i}>...</div>
))}
```

`.map` is just the standard Array method, returning a new array of
elements. React renders an array of elements as a sequence.

**The `key` prop is special.** React uses keys to figure out which items
moved, which were inserted, which were removed when the list changes. If
you skip keys (or use `key={Math.random()}`), React falls back to
"throw everything away and re-render from scratch," which kills performance
and breaks any per-item state (like the open/closed state of a `<details>`
inside the item).

Using `i` (the index) as the key is **fine when items never reorder** and
appending is the only operation. For our chat messages, that's true. For
lists where items can be inserted/removed/reordered, you want a stable ID
(`fact.id`, `message.uuid`, etc.).

### Fragments

When you need to return multiple elements without wrapping them in a
useless `<div>`:

```jsx
return (
  <>
    <Header />
    <Body />
  </>
)
```

`<>...</>` is shorthand for `<React.Fragment>...</React.Fragment>`. We
didn't need this in the chat UI but you'll see it constantly.

### Key insight

> **JSX is JavaScript with syntactic sugar for trees of elements. Anything
> in `{}` is an expression — including `.map`, ternaries, `&&`, and any
> function call you want to embed.**

### Name this

- **JSX expression** — anything between `{}` in JSX.
- **Element key** — the `key` prop on list items.
- **Fragment** — `<>...</>`, returning multiple children without a wrapper.

---

## Stop 8 — Tailwind: utility-first CSS

> **The question:** `className="flex flex-col h-full"`, `text-[10px]`,
> `border-white/10`. What is happening, and isn't this just inline
> styles dressed up?

### The story

Tailwind is **utility-first CSS**: instead of writing semantic class names
like `.chat-header` and a separate CSS file with rules for it, you compose
many tiny single-purpose utility classes directly on the element.

```jsx
<header className="border-b border-white/10 px-5 py-3 flex items-center justify-between">
```

Reads as: "border on the bottom, color is white with 10% opacity, padding
5 horizontal × 3 vertical, display flex, items vertically centered, content
spread to ends."

Each utility maps to a small set of CSS rules. Tailwind's build step scans
your code, finds all the utility classes you used, and generates a CSS file
containing only those rules. Unused utilities don't ship.

### Why this isn't crazy

It looks like inline styles at first, but it solves real problems:

| Old way                                  | Tailwind way                             |
|------------------------------------------|------------------------------------------|
| Make up `.chat-header` class             | Just use `flex items-center px-5 py-3`   |
| Define it in a separate `.css` file      | No separate file                         |
| Cascade rules can conflict / override    | Each utility has one rule, no specificity wars |
| Renaming a class breaks N files          | No naming                                |
| Hard to know what a class does without grep | Class name *is* the behavior          |

The price: HTML gets visually noisy, and refactoring sometimes means moving
many classes. The benefit: locality — when you change a component's look,
you change it right there, not in a separate file with cascade implications.

### Arbitrary values

Sometimes a one-off size or color isn't in Tailwind's preset palette. The
`[brackets]` syntax lets you escape:

```jsx
className="text-[10px]"            // exactly 10px
className="border-white/10"        // white with 10% alpha (preset)
className="w-[360px]"              // exactly 360px wide
```

Use sparingly. If you find yourself reaching for arbitrary values for the
same thing in many places, that's a hint to add it to your `tailwind.config.js`
theme instead.

### Key insight

> **Utility-first CSS trades "elegant class names" for "no separate CSS
> file and no naming or specificity headaches." Once you adjust to the
> visual noise, refactoring components becomes a single-file operation.**

### Name this

- **Utility-first CSS** — the school of thought.
- **Atomic CSS** — same idea, alternate name.
- **JIT (just-in-time) compilation** — Tailwind 3's mode where it scans
  your code at build time and only emits CSS for classes you actually
  used. That's why `text-[10px]` works even though it's never declared
  anywhere — Tailwind sees it and generates the rule on the fly.

---

## Stop 9 — Modern JavaScript idioms in this codebase

A quick reference for the JS idioms we used. Most you probably already know
from Node — included for completeness.

### Destructuring

```jsx
const [input, setInput] = useState('')        // array destructuring
function App({ sessionId, refreshKey }) { }    // object destructuring of props
```

### Spread

```jsx
setMessages(prev => [...prev, newMsg])        // copy array + append
const sortedFacts = [...facts].sort(...)      // copy before sorting (don't mutate)
```

`[...arr]` creates a *new* array with the same elements. Same for objects:
`{...obj, x: 1}`. Used everywhere in React because **mutation doesn't
trigger re-renders** — only setter calls with new references do.

### Optional chaining `?.`

```jsx
scrollRef.current?.scrollTo({...})            // only call if scrollRef.current is non-null
onChatComplete?.()                            // only call if the prop was provided
```

Saves you from `if (x !== null && x !== undefined) x.method()`.

### Nullish coalescing `??`

```jsx
data.facts || []                              // empty array if facts is falsy
fact.importance ?? 0                          // zero only if importance is null/undefined
```

`||` treats `0`, `''`, `false` as "missing." `??` only treats `null` and
`undefined` as missing. Use `??` when zero or empty string are legitimate
values you want to keep.

### `async` / `await`

```jsx
async function sendMessage(text) {
  try {
    const res = await fetch(...)
    const data = await res.json()
    setMessages(prev => [...prev, ...])
  } catch (e) {
    setError(e.message)
  } finally {
    setIsLoading(false)
  }
}
```

`await` only works inside `async` functions. The function returns a Promise
implicitly. `try/catch/finally` is the right pattern for async error
handling — `finally` runs whether the call succeeded or failed, which is
why `setIsLoading(false)` goes there.

### Template literals

```jsx
`Server error: ${res.status}`
`session · ${sessionId.slice(0, 8)}`
```

Backticks, with `${expr}` for embedding. Multi-line strings work without
escaping.

### `crypto.randomUUID()`

```jsx
const newId = crypto.randomUUID()
```

Web platform API for generating a UUIDv4. Available everywhere modern and
in Node 14.17+. No external dependency needed.

### Arrow functions

```jsx
setMessages(prev => [...prev, newMsg])         // single-expression arrow
const handleSubmit = (e) => {                  // multi-statement arrow
  e.preventDefault()
  sendMessage(input)
}
```

Concise function syntax. Crucially, arrow functions **don't have their own
`this`** — they inherit it from the enclosing scope. Less relevant when
writing function components (no `this` involved), but matters in class
contexts.

### Spread in JSX props (rest pattern)

We didn't use it here, but you'll see:

```jsx
<Input {...someObject} />        // spread an object's keys as individual props
function Foo({ x, ...rest }) {}  // collect remaining props
```

---

## Glossary

| Concept                                | Where it shows up in BD-42 web              |
|----------------------------------------|---------------------------------------------|
| Component (function component)         | `App`, `ChatPanel`, `FactsPanel`            |
| `useState` / state hook                | All three components                         |
| `useEffect` / effect hook              | Auto-scroll, fact-fetch, session-clear      |
| `useRef` / ref                         | `scrollRef` in ChatPanel                    |
| Props down, events up                  | `App → ChatPanel/FactsPanel` wiring         |
| Lifting state up                       | `sessionId` lives in `App`                  |
| Callback prop                          | `onChatComplete`, `onClose`, `onReset`      |
| Refresh key / version counter          | `factsRefreshKey`                           |
| Controlled input                       | The textarea in ChatPanel                   |
| Optimistic UI                          | User bubble appears before server reply     |
| Effect cleanup function                | `return () => { cancelled = true }`         |
| Race condition + cleanup               | FactsPanel's fetch effect                   |
| Conditional rendering (`&&`, ternary)  | Empty state, loading state, error display   |
| List rendering + `key`                 | `messages.map`, `sortedFacts.map`           |
| Utility-first CSS / Tailwind           | All `className` strings                     |
| Arbitrary Tailwind values              | `text-[10px]`, `w-[360px]`                  |
| Optional chaining `?.`                 | `scrollRef.current?.scrollTo`               |
| Nullish coalescing `??`                | `fact.importance ?? 0`                      |
| `async`/`await` + try/catch/finally    | `sendMessage`, `fetchFacts`                 |
| `crypto.randomUUID()`                  | New session ID generation                   |
| `localStorage`                         | Session persistence                         |

---

## Where to go next

Two natural extensions whenever you have an hour:

1. **Try breaking things on purpose.** Mutate state instead of using the
   setter (`messages.push(newMsg)` then console.log it — see that the UI
   doesn't update). Remove the `key` prop from `messages.map` (see the
   warning in the console). Skip `e.preventDefault()` in `handleSubmit`
   (watch the page reload). Each "breakage" cements one rule.

2. **Add one small feature** — markdown rendering of BD-42's replies.
   Install `react-markdown` (`npm install react-markdown`), import it in
   `ChatPanel.jsx`, and replace `{m.content}` with `<ReactMarkdown>
   {m.content}</ReactMarkdown>` for the assistant role only. Small, real,
   teaches you how to add a dependency and read its docs in 20 minutes.

If you want a deeper dive on any single stop — the React reconciliation
algorithm (how it diffs the tree to figure out what to update), Tailwind
internals, how `fetch` interacts with CORS, the JS event loop, anything —
say which and I'll write a `03-<topic>.md`.
