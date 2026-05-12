# Game History Split Design

## Goal

Split the existing lobby list into a dedicated game history page, with a navigation entry in the top bar.

## Scope

- `/games` remains the lobby and focuses on creating a new game run.
- `/games/history` becomes the game history page and owns the session list.
- The top navigation exposes a `对局历史` entry from the lobby-facing pages.
- Existing session behaviors stay intact on the history page: refresh sessions, open replay details, resume resumable sessions, show empty state, and show load errors.

## Architecture

- Keep `GamesPage` as the lobby container. It should no longer query or render session history.
- Add a focused `GameHistoryPage` that owns the `listGames` query and `resumeGameRun` mutation.
- Replace `GamesWorkspace` list responsibilities with a create-only lobby workspace.
- Reuse `SessionList` unchanged so replay links and resume controls keep their current contract.
- Extend `AppTopNav` with a first-class history link instead of making each page duplicate the same action.

## Data Flow

- Lobby: renders `CreateGameRunForm`; successful creation already navigates to the live page through the form's existing behavior.
- History: fetches `["games"]`, renders loading/error/empty/list states, invalidates `["games"]` after resume, then navigates to `/games/live/:runId`.

## Testing

- Add route-level coverage that `/games/history` renders the history list and navigation entry.
- Update lobby coverage so `/games` no longer renders session history or fetches sessions for that purpose.
- Preserve resume behavior coverage on the history page.
