# Scweet Simple Surface Plan

Date: 2026-04-10

## Purpose

This note captures the current findings about Scweet's API and product surface, why it no longer feels "simple", and what should be simplified over time without throwing away the power that has already been built.

The goal is not to make Scweet smaller. The goal is to make Scweet easier to understand, easier to adopt, and easier to extend without increasing conceptual mess.

## Executive summary

Scweet started from a simple mental model:

- give it credentials
- scrape tweets or users
- get data back

Scweet is now stronger than that, but the public surface has expanded into a broader system:

- Python library
- CLI
- SQLite-backed account state
- account provisioning
- account pooling
- cooldowns and rate limiting
- proxy handling
- resume support
- output persistence
- hosted actor story on Apify

This is not inherently bad. It means the project grew up. The problem is that the public surface and documentation do not yet reflect that growth cleanly. The result is boundary ambiguity: it is no longer immediately obvious what Scweet is, what the stable beginner path is, and where the advanced operational features begin.

The right response is not to remove power features. The right response is to define boundaries, narrow the main public path, move advanced concerns out of the happy path, and stop mixing multiple execution models into one class.

## Current findings

### 1. Scweet is now more of a scraping system than a simple scraper

The current user-facing promise sounds simple:

- scrape tweets
- scrape followers
- scrape profiles

But the implementation and docs expose a lot more:

- credential provisioning
- SQLite state
- leases
- cooldowns
- daily caps
- proxy checks
- repair flows
- resume checkpoints
- manifest and query ID handling

This is real product value, but it is also why the library no longer feels lightweight.

### 2. The public surface mixes abstraction levels

The high-level API is simple:

- `search(...)`
- `get_profile_tweets(...)`
- `get_followers(...)`
- `get_following(...)`
- `get_user_info(...)`

But the same surface also exposes runtime concerns:

- multiple credential input modes
- provisioning into local DB
- persistent account state
- advanced config
- proxy behavior
- output persistence flags

This makes the main client partly "scraper API" and partly "scraping runtime".

### 3. The constructor is overloaded

Current `Scweet(...)` initialization supports many different sources and operational modes:

- `cookies_file`
- `auth_token`
- `cookies`
- `accounts_file`
- `env_path`
- `db_path`
- `proxy`
- `config`
- `provision`

This is powerful, but it makes the main entry point harder to reason about. It also encourages further growth by adding more constructor arguments over time.

### 4. Output and retrieval are mixed together

Methods like `search(...)` do two different jobs:

- retrieve data
- optionally save data

That leads to public methods with many flags:

- `save`
- `save_format`
- `save_name`
- `save_dir` via config

This increases signature size and cognitive load.

### 5. Configuration breadth is high

`ScweetConfig` has become a broad runtime object. That is useful, but it means a newcomer sees a project that looks operationally dense rather than simple.

The config currently includes:

- core settings
- output settings
- HTTP settings
- rate limiting
- advanced runtime behavior
- manifest behavior

For advanced users this is excellent. For beginners it is too much to absorb early.

### 6. The project currently has multiple product identities

Scweet is simultaneously:

- a local Python scraper
- a CLI
- an account/runtime manager
- a stateful scraping engine
- a hosted actor story on Apify

Again, all of that can coexist, but not if it is all presented as one undifferentiated thing.

### 7. A hosted Apify backend inside `Scweet` would worsen the problem if done naively

Calling the Apify actor directly from Python is a good idea. Hiding that inside the main `Scweet` class is not.

Local execution and hosted actor execution differ in important ways:

- latency
- auth model
- failure model
- result retrieval
- operational expectations

If they are hidden behind one class without clear boundaries, the API will become harder to understand and document.

## Root cause

The core issue is boundary ambiguity.

Scweet has several valid capabilities, but the project does not yet clearly separate:

- simple scraping surface
- advanced local runtime surface
- administrative surface
- hosted surface

That lack of separation creates the feeling of "mess".

## Design principles for a simpler Scweet

These principles should guide future API changes.

### 1. Keep the beginner path extremely small

A new user should be able to understand the main story in under one minute:

- how to authenticate
- how to call one method
- how to get data back

Everything else is secondary.

### 2. Separate execution modes explicitly

The library should not blur:

- local execution
- hosted execution

If hosted execution is added to Python, it should be a separate class.

### 3. Keep the main client high-level

The primary client should expose scraping tasks, not engine internals.

The public surface should answer:

- what do you want to scrape?

not:

- how should leases, provisioning, and persistence be orchestrated?

### 4. Move advanced concerns out of the happy path

Advanced features should still exist, but they should not dominate the first contact surface.

### 5. Prefer separate helpers over one giant constructor

When new input sources or runtime modes are added, they should usually be added as:

- classmethods
- helper loaders
- dedicated advanced objects

not as new arguments on `Scweet(...)`.

### 6. Keep one stable mental model per public object

Each public object should have one job.

Examples:

- `Scweet` = local scraping client
- `ScweetDB` = advanced state/admin interface
- `ScweetApify` = hosted actor client

This is easier to explain and easier to maintain.

## Target public model

### A. Local scraping client

`Scweet` should remain the local scraper.

Its job:

- authenticate
- run scraping calls
- return data

Primary methods:

- `search(...)`
- `get_profile_tweets(...)`
- `get_followers(...)`
- `get_following(...)`
- `get_user_info(...)`

### B. Advanced local state/admin interface

`ScweetDB` should remain real, but it should be treated as an advanced operational/admin tool rather than part of the beginner story.

Its job:

- inspect account state
- repair accounts
- clear cooldowns
- inspect runs and checkpoints

### C. Hosted client

If hosted Apify usage is added to the Python surface, it should be a separate class:

- `ScweetApify`
- or `ScweetHosted`

Its job:

- map high-level scraping calls to actor runs
- wait/poll
- fetch outputs
- normalize results

It should not be merged into `Scweet` behind a `mode="apify"` switch.

## Concrete simplifications to make in the library

This is the main implementation checklist.

### 1. Narrow the main constructor story

Keep the beginner recommendation small:

- `Scweet(auth_token="...")`
- `Scweet(cookies_file="cookies.json")`
- `Scweet(db_path="scweet_state.db")`

Everything else should move toward helper constructors or loader helpers.

Recommended future shape:

```python
Scweet.from_auth_token(...)
Scweet.from_cookies_file(...)
Scweet.from_db(...)
Scweet.from_env(...)
Scweet.from_accounts_file(...)
Scweet.from_cookies(...)
```

Why:

- keeps the main constructor readable
- avoids turning `__init__` into a bag of input modes
- makes source intent explicit

### 2. Stop adding new constructor arguments to `Scweet(...)`

This should be an explicit rule.

If a future feature requires another mode or source, prefer:

- a classmethod
- a request object
- an advanced config/helper

This prevents the constructor from becoming the dumping ground for new capabilities.

### 3. Separate retrieval from persistence

Current methods mix:

- fetching data
- saving data

Longer term, the clean shape is:

- scraping methods return data
- saving is handled by a separate helper or writer

Possible future shapes:

```python
tweets = s.search(...)
s.save(tweets, format="csv")
```

or:

```python
from Scweet import outputs
outputs.write_csv(...)
```

Compatibility path:

- keep `save=` options for now
- de-emphasize them in docs
- introduce explicit output helpers
- deprecate save flags later only if the new flow proves clearly better

### 4. Reduce method signature sprawl with request objects

`search(...)` is powerful, but the signature is large.

Longer term, introduce request objects for dense calls:

- `SearchRequest`
- `FollowsRequest`
- maybe `ProfileRequest`

Possible shape:

```python
req = SearchRequest(
    query="AI",
    since="2026-01-01",
    from_users=["OpenAI"],
    min_likes=50,
    limit=200,
)
tweets = s.search(req)
```

Benefits:

- cleaner signatures
- easier reuse
- easier validation
- easier future extension without growing one public method forever

Compatibility path:

- keep current method signatures
- allow request objects as an additional input
- migrate docs toward request-object usage if it proves cleaner

### 5. Reframe `ScweetConfig` as advanced configuration

`ScweetConfig` is useful, but it should be treated as advanced/runtime configuration rather than the default beginner interface.

Recommended changes:

- keep simple common args directly available where useful
- position `ScweetConfig` as advanced
- document it in tiers: common vs advanced

Possible future improvements:

- a smaller "simple config" layer
- runtime presets
- grouped config sections in code and docs

Examples of future presets:

- `safe_defaults`
- `high_throughput`
- `hostile_network`

This would be easier for users than setting many advanced fields manually.

### 6. Keep `ScweetDB` out of the beginner story

`ScweetDB` is valuable, but it should not feel required to understand the project.

Docs should present it as:

- optional
- advanced
- useful when you need inspection or repair

This reduces perceived complexity without removing the capability.

### 7. Keep exceptions simple at the top level

The beginner mental model should not require understanding every engine-specific exception.

Recommended public error story:

- `ScweetError`
- `AuthError`
- `RateLimitError`
- `NetworkError`
- `ProxyError`

Everything else can still exist, but the docs and simple examples should not make users absorb the full exception taxonomy immediately.

### 8. Keep sync/async support, but do not let it dominate the main story

The current sync + async support is useful.

Do not remove it casually.

But avoid making the top-level experience feel doubled everywhere.

Short-term guidance:

- docs lead with sync examples
- async stays documented and supported

Longer-term optional idea:

- consider a separate `AsyncScweet` if the dual sync/async method naming becomes too noisy

This is lower priority than constructor, persistence, and execution-mode separation.

### 9. Add hosted Python support only as a separate class

If the Apify actor is made callable from Python, do it as:

- `ScweetApify`

not:

- `Scweet(mode="apify")`
- hidden remote/local switching

The hosted client should:

- expose similar high-level methods
- keep hosted semantics explicit
- normalize outputs to stay close to local results

This gives users a migration path without making the main client harder to reason about.

### 10. Make provisioning behavior more explicit in docs and naming

Right now account provisioning into SQLite is powerful, but it is conceptually bigger than many users expect.

Even if the implementation stays the same, the documentation should make this clearer:

- local runs are stateful
- credentials are provisioned
- accounts are reused across runs

This is a strength, but it should be framed as an advanced runtime feature rather than an invisible detail.

## Simplifications for documentation and product positioning

The library surface will feel simpler if the docs follow the same structure.

### Docs should separate three stories

#### 1. Beginner local path

- authenticate
- run one scrape
- get data

#### 2. Advanced local runtime

- pooling
- cooldowns
- proxies
- state DB
- repair and admin

#### 3. Hosted path

- actor on Apify
- managed alternative
- no local ops

Mixing these stories too early creates confusion.

## Things not to do

These are explicit anti-patterns.

### Do not add Apify support directly to `Scweet`

This would mix local and hosted execution into one already-broad object.

### Do not keep growing the constructor

Every new constructor argument makes the main entry point harder to teach and harder to stabilize.

### Do not expose more runtime internals in beginner examples

Beginners should learn scraping tasks first, not runtime orchestration.

### Do not pretend the project is still tiny

Scweet is no longer a very small scraper. The simplification effort should focus on boundary clarity, not on pretending the system is simpler than it is.

## Phased implementation plan

## Phase 1: define and document the simple path

Goal:

- make the stable beginner path explicit without breaking code

Actions:

- decide the three recommended local entry shapes
- update docs and README to center those shapes
- reposition `ScweetDB` and `ScweetConfig` as advanced
- keep advanced features, but move them below the simple path in docs

Output:

- clearer documentation
- no breaking changes yet

## Phase 2: simplify the constructor surface

Goal:

- stop the constructor from carrying every credential and runtime mode

Actions:

- add explicit classmethods:
  - `from_auth_token`
  - `from_cookies_file`
  - `from_db`
  - `from_env`
  - `from_accounts_file`
  - `from_cookies`
- update examples to use these
- keep `__init__` backward compatible

Output:

- clearer code examples
- explicit source intent

## Phase 3: separate fetching from saving

Goal:

- make scraping methods feel smaller and more focused

Actions:

- add explicit output helpers
- start steering examples away from inline `save=` flags
- consider later deprecation of save-related method kwargs if the replacement is clearly better

Output:

- simpler public method story
- cleaner separation of concerns

## Phase 4: reduce signature sprawl with request objects

Goal:

- keep feature richness without giant method signatures

Actions:

- introduce `SearchRequest` support in the public client
- evaluate request objects for follows/profile methods if helpful
- maintain compatibility with direct kwargs initially

Output:

- cleaner call patterns
- easier extensibility

## Phase 5: add hosted Python client, separately

Goal:

- support actor-backed usage from Python without increasing conceptual mess in the local client

Actions:

- add `ScweetApify`
- keep dependency optional
- normalize result shapes
- document local vs hosted clearly

Output:

- better conversion path into Apify
- cleaner execution-mode separation

## Phase 6: cleanup and deprecation pass

Goal:

- remove or de-emphasize historical overload that no longer helps

Actions:

- identify rarely used constructor paths
- identify save-related clutter
- identify advanced config fields that should move into clearer groups or presets
- deprecate carefully, with documentation and migration notes

Output:

- narrower public surface
- less confusion for new users

## Success criteria

The simplification effort is working if:

- a new user can understand the main local flow in under one minute
- the beginner docs do not require understanding DB state, leases, manifests, or repair flows
- the advanced runtime features are still available, but clearly grouped
- the constructor no longer feels like the project index
- hosted usage, if added to Python, is explicit and separate
- the docs and API tell one coherent story instead of several overlapping ones

## Recommended stance going forward

Scweet should be treated as a serious scraping system with a simple front door.

That means:

- keep the power
- simplify the top-level surface
- define boundaries clearly
- avoid mixing execution models
- stop growing the beginner path every time the runtime becomes more capable

The right mental model is not:

- "make Scweet small again"

It is:

- "make Scweet legible again"
