# Users and sharing

With accounts on, each person logs in and has their own adventures. To turn accounts on and
set up the first admin, see [Authentication](authentication.md).

## Admins and members

| | Admin | Member |
| --- | --- | --- |
| See adventures | Every adventure | Their own, and ones shared with them |
| Create adventures | Yes | If the admin allows it |
| Press buttons, change settings, start and stop | Every adventure | Their own |
| Backups, imports, ROMs, Library settings | Yes | No |
| Invite people, change roles | Yes | No |

An adventure belongs to the person who created it. Adventures from before accounts, and
ones loaded from a backup or import, belong to the admin who loaded them.

## Invite someone

1. Open Settings, then People.
2. Choose whether they may create adventures, then press **Make invite link**.
3. Send them the link. It works once and lasts 7 days.

They choose a username and password on the invite page and arrive as a member. In People,
an admin can make someone an admin, turn an account off, or log them out everywhere.
Pending invites are listed there too and can be cancelled.

## Share an adventure

Open Settings, then Sharing, and choose one of your adventures.

- **Let them watch** gives another person with an account the adventure in their Library.
  They see it live but cannot press buttons, change settings or trade with it.
- **Make watch link** creates a link anyone can open without an account, such as a friend in
  a chat. Choose how many days it stays open, or 0 for no end. Turn it off at any time.

Only the owner shares an adventure. A watch link opens that one adventure and nothing else
in the Library.

## Trades

Each player trades only between adventures they own. An admin can set up a trade between
any two adventures.

## Your account

In Settings, under Your account, change your password. Changing it logs you out on every
other device. If PokeSim also uses an identity provider, **Link my identity provider
sign-in** lets you log in either way and keep the same adventures.

If you forget your password, ask an admin to run `pokesim admin reset-password <username>`.
