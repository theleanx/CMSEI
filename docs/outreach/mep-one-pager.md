# CMSEI: a free first look at critical-material exposure
**For manufacturers and the advisers who work with them**

**What it is.** A free, open-source tool that scores how concentrated and hard to replace the supply is for 19 critical materials (gallium, cobalt, rare earths, tantalum, lithium and others), and lets a manufacturer upload a parts list to see which of its products and suppliers lean on the most exposed materials.

**What a plant gets in ten minutes**
- Products ranked by exposure, with the driving material.
- A supplier questionnaire (CSV) to find out where each material actually comes from.
- A what-if: "If China cut off gallium, which of my products are hit, and what might it cost at a price rise I choose?"
- A screen for rules that may apply (DFARS magnets and tantalum, conflict minerals, forced-labor import enforcement), with sources and dates.
- A board-ready PDF.

**Private by design.** The parts list is read in memory and discarded. Nothing is stored. It can also run inside your own network.

**Be clear about its limits.** This is a pilot. Figures come from USGS 2024 tables that a person has not yet checked against the PDFs, and most materials are marked Indicative. In a back-test the index did not beat simply looking at the top producer's share. Use it to decide where to look first, not what to buy.

**Who is behind it.** Maintained by Ankit (theleanx). Methodology, code and back-test are public: github.com/theleanx/CMSEI.

**What we are asking.** Try it with two or three real parts lists and tell us what is wrong, missing or unclear. We will fix what you find.
