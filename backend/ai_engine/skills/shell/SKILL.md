# Workspace commands

Inspect and process files already available to this chat using the isolated workspace command runner.

Use ls to list staged inputs, cat to inspect a small file, head or tail to read up to 200 lines, wc for counts, grep for a literal single-line match, and diff to compare two files. Use only filenames listed by the tool declaration. The runner executes one command in an isolated container using fresh copies of those files. Limits on time and output are set by the account.

For several transformations in one call, use `shell_pipeline`. Use the project-relative `project_name` or chat attachment `filename` from `file_list`. Quote paths with spaces. Simple unquoted `*` and `?` match within one directory level.

Use `|` between stages. `<` reads one file into the first stage. `>` publishes the last stage as a fresh .txt, .md, or valid .json attachment. Project files can be changed with the reviewed patch tool. A pipeline uses the existing project files as input.

Supported options include `cat -n`, `head -n`, `tail -n`, `wc -lwc`, `grep -Finvc -m` with a literal pattern, `sort -nru`, `uniq -cdu`, and `cut -d -f` or `cut -c`. Use `--` before a filename starting with a dash. Inspect all stage statuses and the attachment result before reporting success. A grep stage without a match has status 1 and can pass empty input to the next stage.
