# Market Atlas local data sources and use notice

**Authentic historical data is not distributed in this public checkout.**
Application/compiler code, source-selection metadata and synthetic tests can
be admitted without distributing the dataset. Local setup acquires the
official workbooks and compiles 154 contiguous annual rows spanning 1872–2025
outside the repository. The browser uses the resulting local static build
offline from a twelve-file flat directory; opening the app, installation,
ordinary backup recovery and read-only audit do not download data. Workbooks, observations, compiled builds, exports and private
validation remain outside Git and public CI artifacts/caches. The local build
contains historical values and is intended for localhost use; a public demo,
package, container, release or downloadable build requires a separate data
distribution decision. This notice supplies attribution and provenance, not
a blanket permission grant.

## Selected series and column lineage

The compiler reads legacy XLS workbooks with pandas/xlrd and `header=None`.
Offsets below are zero-based and checked before parsing.

| Selected years | Source and checked columns | Annual derivation |
| --- | --- | --- |
| 1872–1927 stock total return | Robert J. Shiller, `ie_data.xls`, `Data`: date column 0, CPI column 4, real total-return price column 9; headings rows 5–7, monthly data from row 8 | Real index multiplied by CPI, then December-to-December nominal index ratio minus one |
| 1872–1927 ten-year bond total return | Shiller, same sheet, monthly gross total-bond-return factor column 17 | Product of all twelve monthly factors minus one |
| 1872–1927 CPI change | Shiller, same sheet, CPI column 4 | December-to-December ratio minus one |
| 1928 onward stock, bill, ten-year bond total returns | Aswath Damodaran, NYU Stern, `histretSP.xls`, `Returns by year`: checked row 19, data from row 20; year column 0, S&P 500 including dividends column 1, three-month Treasury bill column 3, US ten-year Treasury bond column 4 | Published annual decimal returns; Damodaran wins the overlap |
| 1928 onward CPI change | Damodaran, `Inflation Rate`: checked row 10, data from row 11; year column 0, CPIAUCNS header column 1, annual decimal change column 2 | Published CPI change, identified as BLS CPIAUCNS via FRED/Damodaran |

Before 1928, bills are absent (`null` in JS, empty in CSV) and quality is
`reconstructed`; later quality is `ok`. Output field order is `year`, `stock_tr`,
`bond10_tr`, `tbill_tr`, `cpi_change`, `quality`. Numeric values are decimals
rounded to eight places. The compiler independently reconciles Shiller and
Damodaran stock/bond annual series over 1928–2022 before writing either output.

The versioned acquisition recipe is [`data/sources.json`](data/sources.json).
Its Shiller HTTPS identifier is the XLS link exposed by the
[maintained Shiller source page](https://shillerdata.com/), which describes upstream
Cowles dividend/earnings before 1926, S&P from 1926, Warren–Pearson price-index
inputs before 1913, and BLS CPI thereafter. Thus the selected pre-1928 stock
portion is not wholly from one Cowles contribution. Bond upstream rights and
the original cached workbook's retrieval date remain unresolved. The former
Yale HTTP identifier is not an automatic acquisition fallback.

Damodaran's selected workbook is
[`histretSP.xls`](https://pages.stern.nyu.edu/~adamodar/pc/datasets/histretSP.xls).
The compiler downloads the selected Shiller/NYU workbooks, not FRED directly.
Normal TLS validation and source-specific official HTTPS redirect origins are
mandatory. Both current official identifiers were verified on 2026-10-01 with
strict workbook parsing, the existing anchor/reconciliation checks, full
1872–2025 observation parity and unchanged historical strategy controls.
The raw workbook bytes differ from the older retained inputs; moving URLs do
not promise stable hashes. Record exact raw hashes and preserve each input
object for reproduction. Generation date records compilation, not retrieval
or publisher authentication; a fresh compile uses its actual date.

## Verified private snapshot identifiers

SHA-256 identifies exact local bytes; it proves neither publisher authenticity
nor permission. Private reproduction using these inputs and
`--generated-date 2026-08-20` matched both original outputs byte for byte.

| File | SHA-256 |
| --- | --- |
| Shiller `ie_data.xls` | `0df9392b7dacf91f756e92c8db508ad903c4588b43f3253680eec3dd8b40db68` |
| Damodaran `histretSP.xls` | `12430ac0d0e762b8d0b0a1246089111ec18245278f224e7f6e9925496ca901d8` |
| `market-data.js` | `b5eac2a281fb85e347baf9a05762951f66f17e66fec67f210fd50da61be1ddfa` |
| `market-data.csv` | `fb0c2108361bbf62cb65fa429a3191893d6b7b9e43e238bcdb2e8fa1d0f344f1` |

## Rights status and local-use attribution

The [BLS public-domain statement](https://www.bls.gov/bls/linksite.htm) supports
BLS material, with its stated exceptions and source-citation request. It does
not make either complete workbook public domain.
[Damodaran's published use rules](https://pages.stern.nyu.edu/~adamodar/New_Home_Page/guide.html)
permit regular work/research use, request acknowledgment, and restrict resale;
they do not establish an unrestricted downstream redistribution/sublicensing
license for every upstream contribution. No explicit applicable grant for
public redistribution/adaptation of the Shiller workbook and upstream inputs
was verified. No blanket CC0, MIT, or public-domain data license is asserted.

Credit Robert J. Shiller and Aswath Damodaran/NYU Stern for the locally acquired
series, link their selected workbook identifiers and maintained source pages,
and retain the derivations, period, exact local input identities and applicable
use restrictions. CPI credit identifies BLS and the existing FRED/Damodaran
path. Damodaran's primary-source guidance supports regular local work/research
use. Availability of Shiller's official download establishes acquisition
availability, not unrestricted uses or redistribution of all upstream inputs.
Shiller redistribution remains unresolved, but does not block this code-only
design. Keep generated history local and review a concrete proposed distribution
separately. No owner contact or access-control bypass is part of setup.
