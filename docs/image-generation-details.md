# Image generation details

Opening an image now exposes the inputs behind it. Media's **Image details and
generation** and the image viewer show:

- The image-specific prompt and constraints, including inline tags.
- Global, direct and inherited style/character components in dependency order,
  their declared tags, full bodies, dependencies and reference images.
- Saved assembled prompts and generation settings/receipts when available.
- The assembled prompt and settings from current definitions, using the same
  assembly function as document generation.

Desktop keeps the image beside a scrolling details panel; narrow screens stack
them. Moving to another image updates the details. Keyboard navigation within
prompt text does not advance the image or presentation cue.

## Meaning of the evidence

A canonical candidate's saved prompt is verified only when the receipt's result
hash matches the original/candidate and the saved prompt matches its recorded
hash. Current input drift is shown independently. Incomplete receipts remain
inspectable without a verified claim.

Legacy bundle prompts are often shared across several output files. Their text
is visible with **image association unverified**; current definitions do not
establish historical inputs. Ambiguous original mappings produce unknown
generation inputs. Tags with no declaration in the current style chain are
listed explicitly; no aliases are invented.

All file reads and derived text belong to the bounded inspection snapshot.
Changed saved prompts, definitions, or implicit reference-directory contents
invalidate that snapshot. The shared index contains opaque prompt item IDs;
text is fetched only after opening details. Text stays escaped in the private
workspace and is never added to the authored HTML or its frame messages.
Inspection calls no generation provider and writes no project files.
