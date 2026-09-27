# BeatBox

Create and edit an interactive rhythm sequencer.

Call `render_widget` with format `beatbox` and a JSON string in `content`. Use the following data contract; the server emits the widget, so do not also print the example tags.

This is Interactive rhythmic component.

Sounds: kick, snare, clap, hihat, open_hat, tom, triangle, cowbell.

When a `CURRENT BEATBOX STATE` block is present in the system context, it is the user's latest edited BeatBox widget state. Use it as the source of truth for added tracks, selected instruments, ADSR changes, BPM, bars, and toggled steps. If the user asks to continue, change, or export the beat, base the answer on that current state rather than the older `<beatbox>` JSON in chat history.

Example syntax:

```
<beatbox>
{
  "meta": { "bpm": 100, "bars": 1 },
  "tracks": [
    {
      "id": "track_1",
      "type": "drum",
      "drum": "kick",
      "steps": [1,0,0,0,1,0,0,0,1,0,0,0,1,0,0,0],
      "adsr": { "attack": 0.001, "decay": 0.1, "sustain": 0, "release": 0.05 }
    }
  ],
  "isPlaying": false,
  "currentStep": 0,
  "timerId": null
}
</beatbox>
```
