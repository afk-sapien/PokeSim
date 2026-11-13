# Multi-user UI checklist

A person runs each item in a real browser, as a user would. Use the API only where an item
says API. Mark each item pass or fail, and keep a screenshot of every failure.

The automated tests already cover the share roles, give away, delete a user, running limits,
password change and the login redirect. This list covers what they do not: the first run,
an upgrade, two people at once, and the pages on a phone.

## Before you start

1. Run a throwaway copy of the release candidate on `127.0.0.1` with an empty data folder,
   `AUTH=accounts`, and no `POKESIM_ADMIN_USER` or `POKESIM_ADMIN_PASSWORD`. Give it a port
   no other PokeSim uses.
2. Use made-up accounts only: `qa-admin`, `qa-alice` and `qa-bob` (both may create
   adventures), and `qa-carol` and `qa-dave` (both may not). Keep their passwords in a scratch
   file outside the repository.
3. Use two browser profiles for two people at once. `127.0.0.1` and `localhost` keep separate
   cookies, so one profile on each works too.
4. Keep at most two adventures running. Use Red, which is the lightest game.
5. For the upgrade section, run a second throwaway copy that starts from `v0.7.0`.

"Refused" means the page or response says not found or not allowed, and shows none of the
other person's data.

## 1. Fresh install and the first admin

| ID | Action | Expected |
| --- | --- | --- |
| F1 | Open the Library address on the fresh copy. | The setup page opens. No Library content shows. |
| F2 | Open `/login`. | It goes to the setup page. |
| F3 | Open `/api/v1/adventures` in the address bar. | Refused, with no adventure list. |
| F4 | On setup, type two different passwords and submit. | The page says they do not match. No account is made. |
| F5 | Look for the setup code field. If it shows, submit a wrong code. | A wrong code is refused. From this machine the code may be skipped. Record which. |
| F6 | Finish setup as `qa-admin`. | The Library opens, signed in, empty, with People and Game cartridges in Settings. |
| F7 | Open `/setup` again. | It goes to the login page or the Library. Setup cannot run twice. |
| F8 | In Settings, Game cartridges, upload the Red cartridge. | Red is on the shelf. |

## 2. Sign in and sign out

| ID | Action | Expected |
| --- | --- | --- |
| L1 | Press **Log out**. | The login page opens. Back and reload show no Library content. |
| L2 | Log in with the right username and password. | The Library opens. |
| L3 | Log in with a wrong password. | "Wrong username or password". You stay on the login page. |
| L4 | Log in with a username that does not exist. | The same message as L3, so it does not tell which part was wrong. |
| L5 | Log in with the username in capitals, such as `QA-ADMIN`. | It logs in. Usernames ignore case. |
| L6 | Signed out, open an adventure's game page by its address. | The login page opens. After logging in you return to that game page. |
| L7 | Signed out, open `/login?next=https://example.com` and log in. | You stay on this site. |
| L8 | Do this last. Type eight wrong passwords, a few seconds apart, then the right one at once. The first five are free and the wait then doubles from 1 second, so fewer misses leave no wait to see. | The page says "Too many attempts. Try again in N seconds." After the wait the right password works. |

## 3. Creating users and roles

| ID | Action | Expected |
| --- | --- | --- |
| U1 | As admin, in Settings, People, tick **Can create adventures** and press **Make invite link**. | A link shows and the invite is listed as pending. |
| U2 | Open the link in the second profile and choose `qa-alice` and a password. | The Library opens for `qa-alice` as a member. |
| U3 | Repeat for `qa-bob` (may create), `qa-carol` and `qa-dave` (may not). | Each arrives as a member. People lists five people with the right **Can create** state. |
| U4 | Open the used invite link again. | "This invite link has expired or was already used." |
| U5 | Make an invite, press **Cancel invite**, then open its link. | The same expired message. |
| U6 | On a new invite, choose a username that is taken. | Refused with a clear message. The invite still works. |
| U7 | As `qa-alice`, open Settings. | No People, Game cartridges, Backups, Notifications or Running adventures. Your account and Sharing show. |
| U8 | As `qa-alice`, open `/docs`. As admin, open `/docs`. | 404 for the member. The API reference for the admin. |
| U9 | As `qa-carol`, try to create an adventure. | It is not offered, or it is refused with the reason. |
| U10 | As admin, press **Make admin** for `qa-bob`, then **Make member**. | After a reload `qa-bob` sees People, and after the second change no longer does. |
| U11 | As `qa-alice`, open `/api/v1/users` in the address bar (API). | Refused. |

## 4. Each person's adventures stay private

`qa-alice` creates and starts Alice Red. `qa-bob` creates and starts Bob Red. Nothing is
shared yet. "Replays" here means the journal's event pages with **Rewind**, and saves means
save states and the save download.

| ID | Action | Expected |
| --- | --- | --- |
| P1 | Open the Library as each of `qa-alice`, `qa-bob` and admin. | Alice sees only Alice Red, Bob only Bob Red, the admin both. |
| P2 | As `qa-bob`, open Alice Red's game page by its address, `/games/<id>/`. | Refused. No screen, name or party shows. |
| P3 | As `qa-bob`, open `/view/<Alice Red id>/`. | Refused. |
| P4 | As `qa-bob`, open Alice Red's Journal, Pokédex, PC, Stats and Trading pages by address. | Each is refused. |
| P5 | As `qa-bob`, open one of Alice Red's event pages, `/games/<id>/events/<n>`. | Refused. No rewind. |
| P6 | As `qa-bob`, open Alice Red's `api/states` and `api/export-save` (API). | Refused. No save is listed or downloaded. |
| P7 | As `qa-bob`, open `/api/v1/adventures/<Alice Red id>` (API). | Refused. |
| P8 | As `qa-bob`, send stop, pause and settings changes for Alice Red from the browser console (API). | Each is refused. Alice Red keeps running unchanged. |
| P9 | As `qa-bob`, open Settings, Sharing. | Only Bob Red is in the adventure list. |
| P10 | As `qa-bob`, open Inbox and the Trading page of Bob Red. | Nothing about Alice Red. Trade with lists only Bob's own adventures. |
| P11 | As `qa-bob`, open New adventure and the cartridge list. | Red shows. The adventures playing it are only Bob's own. |
| P12 | As `qa-bob`, open `/api/v1/backups` (API). | Refused. |
| P13 | As admin, open Alice Red's game page, journal and an event page. | All open, since an admin counts as owner. |
| P14 | As `qa-alice`, share Alice Red with `qa-dave` as **Can watch**. | Dave's Library lists Alice Red as shared. Bob's and Carol's still do not. |

## 5. Start, pause, resume and delete by role

`qa-alice` shares Alice Red with `qa-bob` as **Can manage** and `qa-carol` as **Can play**.
`qa-dave` keeps **Can watch**.

| ID | Action | Expected |
| --- | --- | --- |
| R1 | As owner `qa-alice`, press Pause, then Resume on the game page. | It pauses, then plays again. |
| R2 | As manager `qa-bob`, press Pause, then Resume. | Both work. |
| R3 | As player `qa-carol`, look for Pause, then press **Take control**. | No Pause. Take control works. Resume works only while she holds control. |
| R4 | As watcher `qa-dave`, open the game page. | No controls and no Take control. |
| R5 | As manager, player and watcher, look for Start and Stop in the Library. | Not offered, since only the owner and admins start and stop. |
| R6 | As owner, press Stop in the Library, then Start. | Stopped with saves kept, then running again. |
| R7 | As `qa-alice`, create Alice Spare and share it with `qa-bob`. As `qa-bob`, look for Delete on it. | Not offered to the manager. |
| R8 | As `qa-alice`, press Delete on Alice Spare and type a wrong name. | Refused. Nothing is deleted. |
| R9 | Type the right name. | Alice Spare is gone from Alice's and Bob's Libraries. |
| R10 | As `qa-bob`, create Bob Spare. As admin, delete it. | It is deleted for the admin and gone from Bob's Library. |
| R11 | As `qa-dave`, try Delete on Alice Red, by the API from the console. | Refused. Alice Red is unchanged. |

## 6. Two people at once

| ID | Action | Expected |
| --- | --- | --- |
| T1 | `qa-alice` in one profile, `qa-bob` in the other, both on their Libraries. | Each sees their own name and list. Neither is logged out by the other. |
| T2 | Both open Alice Red. `qa-bob` presses Pause. | Alice's page shows Paused within a few seconds. |
| T3 | `qa-carol` takes control. `qa-alice` presses **Take control back**. | Carol's page says control was taken back. |
| T4 | `qa-bob` logs out. | Alice's profile stays logged in. |
| T5 | `qa-alice` logs in on both profiles, then logs out of one. | The other stays logged in. |

## 7. Sessions and passwords

| ID | Action | Expected |
| --- | --- | --- |
| X1 | Logins last 14 days. On the throwaway copy, set one login's expiry to the past in its database, then reload that browser. | The login page opens. After logging in you return. |
| X2 | Leave a game page open, end its session as in X1, then press a control. | It asks you to log in again and does not fail silently. |
| X3 | As `qa-alice`, in Settings, Your account, change the password with a wrong current password. | Refused. |
| X4 | Change it with two different new passwords. | "The two new passwords do not match." |
| X5 | Change it correctly. | "Password changed. Your other sessions have ended." |
| X6 | In Alice's other profile, do anything. | The login page opens. |
| X7 | Log in with the old password, then the new one. | The old one is refused, the new one works. |
| X8 | As admin, press **Log out everywhere** for `qa-bob`. | Bob's open page goes to the login page on his next action. |

## 8. An admin turns off or deletes a user

| ID | Action | Expected |
| --- | --- | --- |
| D1 | As admin, press **Turn off** for `qa-bob` while he is logged in. | His next action goes to the login page and his login is refused. |
| D2 | As admin, look at Bob Red, and as `qa-alice` at Alice Red's Sharing. | Bob Red still exists and is kept. Bob's share on Alice Red no longer lets him in. |
| D3 | Press **Turn on** for `qa-bob` and log in as him. | He logs in and sees Bob Red again. |
| D4 | Delete `qa-dave`, who owns nothing. | His account is gone and Alice Red's Sharing no longer lists him. |
| D5 | Delete `qa-bob` and choose **Archive it** for Bob Red. | Bob Red is stopped and archived under the admin, who can restore it. Nothing is deleted. |
| D6 | Log in as the deleted `qa-bob`. | "Wrong username or password". |
| D7 | As admin, look for **Delete user** on your own row. | Not offered, or refused. The last admin cannot be deleted. |

## 9. Upgrade from a 0.7.0 data folder

| ID | Action | Expected |
| --- | --- | --- |
| G1 | Run `v0.7.0` with `AUTH=none` on an empty folder. Add Red, create Old Red, let it play a few minutes, note its playtime and journal count, stop it, then stop the server. | A single-user Library with one stopped adventure. |
| G2 | Start the release candidate on that folder with `AUTH` unset. | The Library opens with no login. Old Red is there unchanged. |
| G3 | Restart it with `AUTH=accounts`. | The address goes to the setup page. |
| G4 | Finish setup as the first admin. | Old Red is listed and owned by the admin, with the same playtime and journal. |
| G5 | Start Old Red and open its game page, journal and an event page. | It plays from where it stopped. Pages and saves work. |
| G6 | Signed out, open Old Red's old `/view/` link. As admin, open Sharing. | The link asks for a login. Sharing shows the old link with **Make a link**. |
| G7 | Invite a member and log in as them. | The member does not see Old Red. |

## 10. Phone width

Set the browser to 390 by 844.

| ID | Action | Expected |
| --- | --- | --- |
| M1 | Open `/login`. | Fields and the Log in button fit. No sideways scroll. |
| M2 | Submit a wrong password. | The message fits and is readable. |
| M3 | Open `/setup` on a fresh copy. | Fits, no sideways scroll. |
| M4 | Open an invite link. | Fits, no sideways scroll. |
| M5 | As admin, open Settings, People. | Every person's row and buttons fit and none is cut off. |
| M6 | Open Settings, Your account and Sharing. | Fits, no sideways scroll. |
| M7 | Open the Library header as a member. | Inbox, the user name and Log out fit. |
