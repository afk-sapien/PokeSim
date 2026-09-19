# Party menu label repair

## Verified failure

Automatic exchange `29164c1ad4004d748619352b514d3430` exhausted its travel deadline while Blue Ripple was using Cut in Viridian City. Its selected partner knew Cut, but another party member was named GRIMBISCUT. The policy searched the entire screen for the substring CUT and selected the nickname row instead of the action menu row.

The retained checkpoint reproduced the loop for 108,000 emulated frames without reaching a destination PC. The exchange later succeeded on retry, so the failure was intermittent in live play.

## Change

Party field actions and reordering now match the complete label to the right of the action menu cursor. Text in party nicknames and partial matches no longer select a menu action. Missing actions still back out safely.

Seven regression cases cover Cut, Surf, Fly, Strength, cursor movement, missing or partial labels, and Switch. The focused policy suite passed all 60 tests.

The complete Python suite passed 952 tests with 40 skipped. It reported one existing dependency deprecation warning.

## Cartridge replay

The corrected policy reached a destination PC from the same checkpoint in 1,466 emulated frames with no error, using ordinary button inputs. The replay did not edit the live campaign or the ROM.

Private checkpoint and trace evidence is preserved in the smoke application's observations directory under `party-menu-labels-20260917`.
