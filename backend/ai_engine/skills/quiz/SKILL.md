# Quiz

Create interactive learning quizzes.

Call `render_widget` with format `quiz` and a JSON string in `content`. Use the following data contract; the server emits the widget, so do not also print the example tags.

Interactive learning widget.

Example syntax:

```
<quiz>
{
  "cards": [
    {
      "question": "Question text (max. 100 chars)",
      "choices": ["Option 1", "Option 2", "Option 3"],
      "correct_index": 0,
      "hint": "Short hint (max. 100 chars)"
    }
  ],
  "nextQuizTitle": "Next topic"
}
</quiz>
```
