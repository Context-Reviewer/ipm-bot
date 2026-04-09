# Save Schema

Working schema source:

- recovered `Assembly-CSharp.dll`
- recovered `dump.cs`
- live `playerInfo.dat` samples

Primary type of interest:

- `SaveLoad.PlayerData`

Initial mapping work should focus on:

- premium currencies
- ad / reward state
- save / cloud bookkeeping
- event / miner-pass payload

Working notes:

- [Player Data Offset Notebook](player_data_offset_notebook.md)
- [DummyDll PlayerData Anchor](dummydll_playerdata_anchor.md)
- [Ads Class Runtime Notes](../experiments/ads_class_runtime_notes.md)
