# Verra Project Hub Documentation


- **DSP Directory** — provider listings and detailed provider profiles at
  `dsp-directory/`.
- **Release Notes** — Project Hub release updates at `releases/`.
- **Guardian Onboarding Guide** — onboarding instructions at
  `guardian-onboarding/`.

## DSP Directory maintenance

The directory interface is maintained in `dsp-directory/index.html`, and
provider records are stored in `dsp-directory/dsp-data.json`. Keep both
files together when serving the directory. Each record's stable `id` is used to
create a shareable detail page at `dsp-directory/<id>/` (for example,
`dsp-directory/belian/`). GitHub Pages serves a provider-specific entry
HTML file at each route; the existing `index.html?dsp=<id>` query URL also
continues to work relative to the directory route.

Each provider also has a static route at `dsp-directory/<id>/` (for
example, `dsp-directory/belian/`). These provider-specific HTML entry
points forward to the shared detail renderer and keep the provider ID in the
URL, allowing Project Hub to embed each provider at its own route. Add a
matching `dsp-directory/<id>/index.html` when adding a provider.

The detail page is rendered from the selected record rather than provider-specific
markup. CSV fields marked for removal are omitted from the data file, and retained
fields use the renamed headings. To add or update a provider, edit its record in
`dsp-data.json`.

For local development, serve the repository root over HTTP rather than opening
an HTML file as a `file://` URL. This allows the browser to fetch the directory
data and access all three pages at their documented paths.

## Project Hub API integration status

The directory groups providers by the `apiStatus` value in each provider record:
`Completed` means the provider's Project Hub API integration is complete; other
statuses, including `In progress`, are grouped as not yet having a completed
Project Hub integration. This status does not indicate whether the provider has
its own API. For providers without a completed Project Hub integration, users
should contact the provider to confirm delivery options and coordinate with
their project team about providing the data to Project Hub.

The Project Hub page supplies the shared portal shell.
`dsp-directory/index.html` has a full-width in-frame toolbar for switching
between the DSP directory and API documentation; its API Documentation link
uses the embedding Project Hub origin when available.

The GitHub Pages site is published from the repository root. Since this
repository is named `doc`, the public DSP directory path is
`/doc/dsp-directory/` (for example, `/doc/dsp-directory/belian/`).
