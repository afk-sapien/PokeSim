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

- **Share** gives another person with an account the adventure in their Library. Choose
  what they can do:
  - **Can watch**: they see it live but cannot press buttons, change settings or trade.
  - **Can play**: they can also take control and play by hand.
  - **Can manage**: they can also pause, save, change speed, load a save state and set
    trading preferences. Only the owner restarts, exports, deletes or shares it.
- **Make watch link** creates a link anyone can open without an account, such as a friend in
  a chat. Choose how many days it stays open, or 0 for no end. Turn it off at any time.

Only the owner shares an adventure. A watch link opens that one adventure and nothing else
in the Library. Change what someone can do from the list of people, or stop sharing.

An adventure from before accounts had a `/view/` link. That link stops working when accounts
turn on. Sharing shows it with a **Make a link** button that makes a watch link in its place.

## Take control

One person plays by hand at a time. Press **Take control** on the game page. If someone else
already has control, you join a line and they choose **Hand over** or **Refuse**. An owner or
manager can always press **Take control back**.

Control ends when you press **Let AI play**, when you press no buttons for 2 minutes, when
your page closes, or when a trade or backup starts. You get a warning 30 seconds before an
idle end. The next person in line gets control then. The owner chooses whether the AI plays
again or the game stays paused when control ends. To change the idle time, set
`CONTROL_IDLE_SECONDS` (30 or more).

Loading a save state or restarting first saves a checkpoint, so a mistake can be undone.

## Trades

You build trades by hand only between adventures you own. An admin can set up a trade
between any two adventures.

To trade with someone else, send an offer. Their adventure must be shared with you and
its owner must switch on **Open to offers** on its Trading page. Only the owner answers
an offer. See [Trade offers](trading.md#trade-offers).

Automatic trading pairs two people's adventures only when both owners switch on **Auto
trading with other people**. Otherwise it pairs only adventures with the same owner.

## Inbox

**Inbox** in the Library header shows how many items you have not read. Open it to see
them, newest first. You get an item when:

1. Someone sends an offer to your adventure, or answers, or lets expire, an offer you sent.
2. A trade between your adventure and someone else's finishes.
3. Someone asks for control while you hold it, or asks for control of your adventure.
4. An owner or manager takes control back from you.
5. Someone shares an adventure with you.

Nothing arrives for your own actions or for trades between your own adventures. Select
an item to open its page and mark it read, or select **Mark all read**. PokeSim keeps
your newest 200 items.

Alerts sent to ntfy, Discord or Telegram stay with admins, under Notifications.

## Your account

In Settings, under Your account, change your password. Changing it logs you out on every
other device. If PokeSim also uses an identity provider, **Link my identity provider
sign-in** lets you log in either way and keep the same adventures.

If you forget your password, ask an admin to run `pokesim admin reset-password <username>`.
