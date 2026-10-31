from __future__ import annotations

import json
from textwrap import dedent
from typing import Any

# frontend-vendor:begin preact hooks htm kit lucide=ArrowLeft,FileText,FolderOpen,GitBranch,Inbox,Link,Loader,RefreshCw,Settings,Shield,Trash2,CheckCircle,Edit,Eye font:dm-sans font:jetbrains-mono font:space-grotesk
FRONTEND_VENDOR_HTML = r"""<!--
The MIT License (MIT)

Copyright (c) 2015-present Jason Miller

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

-->
<!--

                                 Apache License
                           Version 2.0, January 2004
                        http://www.apache.org/licenses/

   TERMS AND CONDITIONS FOR USE, REPRODUCTION, AND DISTRIBUTION

   1. Definitions.

      "License" shall mean the terms and conditions for use, reproduction,
      and distribution as defined by Sections 1 through 9 of this document.

      "Licensor" shall mean the copyright owner or entity authorized by
      the copyright owner that is granting the License.

      "Legal Entity" shall mean the union of the acting entity and all
      other entities that control, are controlled by, or are under common
      control with that entity. For the purposes of this definition,
      "control" means (i) the power, direct or indirect, to cause the
      direction or management of such entity, whether by contract or
      otherwise, or (ii) ownership of fifty percent (50%) or more of the
      outstanding shares, or (iii) beneficial ownership of such entity.

      "You" (or "Your") shall mean an individual or Legal Entity
      exercising permissions granted by this License.

      "Source" form shall mean the preferred form for making modifications,
      including but not limited to software source code, documentation
      source, and configuration files.

      "Object" form shall mean any form resulting from mechanical
      transformation or translation of a Source form, including but
      not limited to compiled object code, generated documentation,
      and conversions to other media types.

      "Work" shall mean the work of authorship, whether in Source or
      Object form, made available under the License, as indicated by a
      copyright notice that is included in or attached to the work
      (an example is provided in the Appendix below).

      "Derivative Works" shall mean any work, whether in Source or Object
      form, that is based on (or derived from) the Work and for which the
      editorial revisions, annotations, elaborations, or other modifications
      represent, as a whole, an original work of authorship. For the purposes
      of this License, Derivative Works shall not include works that remain
      separable from, or merely link (or bind by name) to the interfaces of,
      the Work and Derivative Works thereof.

      "Contribution" shall mean any work of authorship, including
      the original version of the Work and any modifications or additions
      to that Work or Derivative Works thereof, that is intentionally
      submitted to Licensor for inclusion in the Work by the copyright owner
      or by an individual or Legal Entity authorized to submit on behalf of
      the copyright owner. For the purposes of this definition, "submitted"
      means any form of electronic, verbal, or written communication sent
      to the Licensor or its representatives, including but not limited to
      communication on electronic mailing lists, source code control systems,
      and issue tracking systems that are managed by, or on behalf of, the
      Licensor for the purpose of discussing and improving the Work, but
      excluding communication that is conspicuously marked or otherwise
      designated in writing by the copyright owner as "Not a Contribution."

      "Contributor" shall mean Licensor and any individual or Legal Entity
      on behalf of whom a Contribution has been received by Licensor and
      subsequently incorporated within the Work.

   2. Grant of Copyright License. Subject to the terms and conditions of
      this License, each Contributor hereby grants to You a perpetual,
      worldwide, non-exclusive, no-charge, royalty-free, irrevocable
      copyright license to reproduce, prepare Derivative Works of,
      publicly display, publicly perform, sublicense, and distribute the
      Work and such Derivative Works in Source or Object form.

   3. Grant of Patent License. Subject to the terms and conditions of
      this License, each Contributor hereby grants to You a perpetual,
      worldwide, non-exclusive, no-charge, royalty-free, irrevocable
      (except as stated in this section) patent license to make, have made,
      use, offer to sell, sell, import, and otherwise transfer the Work,
      where such license applies only to those patent claims licensable
      by such Contributor that are necessarily infringed by their
      Contribution(s) alone or by combination of their Contribution(s)
      with the Work to which such Contribution(s) was submitted. If You
      institute patent litigation against any entity (including a
      cross-claim or counterclaim in a lawsuit) alleging that the Work
      or a Contribution incorporated within the Work constitutes direct
      or contributory patent infringement, then any patent licenses
      granted to You under this License for that Work shall terminate
      as of the date such litigation is filed.

   4. Redistribution. You may reproduce and distribute copies of the
      Work or Derivative Works thereof in any medium, with or without
      modifications, and in Source or Object form, provided that You
      meet the following conditions:

      (a) You must give any other recipients of the Work or
          Derivative Works a copy of this License; and

      (b) You must cause any modified files to carry prominent notices
          stating that You changed the files; and

      (c) You must retain, in the Source form of any Derivative Works
          that You distribute, all copyright, patent, trademark, and
          attribution notices from the Source form of the Work,
          excluding those notices that do not pertain to any part of
          the Derivative Works; and

      (d) If the Work includes a "NOTICE" text file as part of its
          distribution, then any Derivative Works that You distribute must
          include a readable copy of the attribution notices contained
          within such NOTICE file, excluding those notices that do not
          pertain to any part of the Derivative Works, in at least one
          of the following places: within a NOTICE text file distributed
          as part of the Derivative Works; within the Source form or
          documentation, if provided along with the Derivative Works; or,
          within a display generated by the Derivative Works, if and
          wherever such third-party notices normally appear. The contents
          of the NOTICE file are for informational purposes only and
          do not modify the License. You may add Your own attribution
          notices within Derivative Works that You distribute, alongside
          or as an addendum to the NOTICE text from the Work, provided
          that such additional attribution notices cannot be construed
          as modifying the License.

      You may add Your own copyright statement to Your modifications and
      may provide additional or different license terms and conditions
      for use, reproduction, or distribution of Your modifications, or
      for any such Derivative Works as a whole, provided Your use,
      reproduction, and distribution of the Work otherwise complies with
      the conditions stated in this License.

   5. Submission of Contributions. Unless You explicitly state otherwise,
      any Contribution intentionally submitted for inclusion in the Work
      by You to the Licensor shall be under the terms and conditions of
      this License, without any additional terms or conditions.
      Notwithstanding the above, nothing herein shall supersede or modify
      the terms of any separate license agreement you may have executed
      with Licensor regarding such Contributions.

   6. Trademarks. This License does not grant permission to use the trade
      names, trademarks, service marks, or product names of the Licensor,
      except as required for reasonable and customary use in describing the
      origin of the Work and reproducing the content of the NOTICE file.

   7. Disclaimer of Warranty. Unless required by applicable law or
      agreed to in writing, Licensor provides the Work (and each
      Contributor provides its Contributions) on an "AS IS" BASIS,
      WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
      implied, including, without limitation, any warranties or conditions
      of TITLE, NON-INFRINGEMENT, MERCHANTABILITY, or FITNESS FOR A
      PARTICULAR PURPOSE. You are solely responsible for determining the
      appropriateness of using or redistributing the Work and assume any
      risks associated with Your exercise of permissions under this License.

   8. Limitation of Liability. In no event and under no legal theory,
      whether in tort (including negligence), contract, or otherwise,
      unless required by applicable law (such as deliberate and grossly
      negligent acts) or agreed to in writing, shall any Contributor be
      liable to You for damages, including any direct, indirect, special,
      incidental, or consequential damages of any character arising as a
      result of this License or out of the use or inability to use the
      Work (including but not limited to damages for loss of goodwill,
      work stoppage, computer failure or malfunction, or any and all
      other commercial damages or losses), even if such Contributor
      has been advised of the possibility of such damages.

   9. Accepting Warranty or Additional Liability. While redistributing
      the Work or Derivative Works thereof, You may choose to offer,
      and charge a fee for, acceptance of support, warranty, indemnity,
      or other liability obligations and/or rights consistent with this
      License. However, in accepting such obligations, You may act only
      on Your own behalf and on Your sole responsibility, not on behalf
      of any other Contributor, and only if You agree to indemnify,
      defend, and hold each Contributor harmless for any liability
      incurred by, or claims asserted against, such Contributor by reason
      of your accepting any such warranty or additional liability.

   END OF TERMS AND CONDITIONS

   APPENDIX: How to apply the Apache License to your work.

      To apply the Apache License to your work, attach the following
      boilerplate notice, with the fields enclosed by brackets "[]"
      replaced with your own identifying information. (Don't include
      the brackets!)  The text should be enclosed in the appropriate
      comment syntax for the file format. We also recommend that a
      file or class name and description of purpose be included on the
      same "printed page" as the copyright notice for easier
      identification within third-party archives.

   Copyright 2018 Google Inc.

   Licensed under the Apache License, Version 2.0 (the "License");
   you may not use this file except in compliance with the License.
   You may obtain a copy of the License at

       http://www.apache.org/licenses/LICENSE-2.0

   Unless required by applicable law or agreed to in writing, software
   distributed under the License is distributed on an "AS IS" BASIS,
   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
   See the License for the specific language governing permissions and
   limitations under the License.
-->
<!--
ISC License

Copyright (c) 2026 Lucide Icons and Contributors

Permission to use, copy, modify, and/or distribute this software for any
purpose with or without fee is hereby granted, provided that the above
copyright notice and this permission notice appear in all copies.

THE SOFTWARE IS PROVIDED "AS IS" AND THE AUTHOR DISCLAIMS ALL WARRANTIES
WITH REGARD TO THIS SOFTWARE INCLUDING ALL IMPLIED WARRANTIES OF
MERCHANTABILITY AND FITNESS. IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR
ANY SPECIAL, DIRECT, INDIRECT, OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES
WHATSOEVER RESULTING FROM LOSS OF USE, DATA OR PROFITS, WHETHER IN AN
ACTION OF CONTRACT, NEGLIGENCE OR OTHER TORTIOUS ACTION, ARISING OUT OF
OR IN CONNECTION WITH THE USE OR PERFORMANCE OF THIS SOFTWARE.

---

The following Lucide icons are derived from the Feather project:

airplay, alert-circle, alert-octagon, alert-triangle, aperture, arrow-down-circle, arrow-down-left, arrow-down-right, arrow-down, arrow-left-circle, arrow-left, arrow-right-circle, arrow-right, arrow-up-circle, arrow-up-left, arrow-up-right, arrow-up, at-sign, calendar, cast, check, chevron-down, chevron-left, chevron-right, chevron-up, chevrons-down, chevrons-left, chevrons-right, chevrons-up, circle, clipboard, clock, code, columns, command, compass, corner-down-left, corner-down-right, corner-left-down, corner-left-up, corner-right-down, corner-right-up, corner-up-left, corner-up-right, crosshair, database, divide-circle, divide-square, dollar-sign, download, external-link, feather, frown, hash, headphones, help-circle, info, italic, key, layout, life-buoy, link-2, link, loader, lock, log-in, log-out, maximize, meh, minimize, minimize-2, minus-circle, minus-square, minus, monitor, moon, more-horizontal, more-vertical, move, music, navigation-2, navigation, octagon, pause-circle, percent, plus-circle, plus-square, plus, power, radio, rss, search, server, share, shopping-bag, sidebar, smartphone, smile, square, table-2, tablet, target, terminal, trash-2, trash, triangle, tv, type, upload, x-circle, x-octagon, x-square, x, zoom-in, zoom-out

The MIT License (MIT) (for the icons listed above)

Copyright (c) 2013-present Cole Bemis

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

-->
<!--
Copyright 2014 The DM Sans Project Authors (https://github.com/googlefonts/dm-fonts) DMSans-Italic[opsz,wght].ttf: Copyright 2014 The DM Sans Project Authors (https://github.com/googlefonts/dm-fonts)

This Font Software is licensed under the SIL Open Font License, Version 1.1.
This license is copied below, and is also available with a FAQ at:
http://scripts.sil.org/OFL


-----------------------------------------------------------
SIL OPEN FONT LICENSE Version 1.1 - 26 February 2007
-----------------------------------------------------------

PREAMBLE
The goals of the Open Font License (OFL) are to stimulate worldwide
development of collaborative font projects, to support the font creation
efforts of academic and linguistic communities, and to provide a free and
open framework in which fonts may be shared and improved in partnership
with others.

The OFL allows the licensed fonts to be used, studied, modified and
redistributed freely as long as they are not sold by themselves. The
fonts, including any derivative works, can be bundled, embedded,
redistributed and/or sold with any software provided that any reserved
names are not used by derivative works. The fonts and derivatives,
however, cannot be released under any other type of license. The
requirement for fonts to remain under this license does not apply
to any document created using the fonts or their derivatives.

DEFINITIONS
"Font Software" refers to the set of files released by the Copyright
Holder(s) under this license and clearly marked as such. This may
include source files, build scripts and documentation.

"Reserved Font Name" refers to any names specified as such after the
copyright statement(s).

"Original Version" refers to the collection of Font Software components as
distributed by the Copyright Holder(s).

"Modified Version" refers to any derivative made by adding to, deleting,
or substituting -- in part or in whole -- any of the components of the
Original Version, by changing formats or by porting the Font Software to a
new environment.

"Author" refers to any designer, engineer, programmer, technical
writer or other person who contributed to the Font Software.

PERMISSION & CONDITIONS
Permission is hereby granted, free of charge, to any person obtaining
a copy of the Font Software, to use, study, copy, merge, embed, modify,
redistribute, and sell modified and unmodified copies of the Font
Software, subject to the following conditions:

1) Neither the Font Software nor any of its individual components,
in Original or Modified Versions, may be sold by itself.

2) Original or Modified Versions of the Font Software may be bundled,
redistributed and/or sold with any software, provided that each copy
contains the above copyright notice and this license. These can be
included either as stand-alone text files, human-readable headers or
in the appropriate machine-readable metadata fields within text or
binary files as long as those fields can be easily viewed by the user.

3) No Modified Version of the Font Software may use the Reserved Font
Name(s) unless explicit written permission is granted by the corresponding
Copyright Holder. This restriction only applies to the primary font name as
presented to the users.

4) The name(s) of the Copyright Holder(s) or the Author(s) of the Font
Software shall not be used to promote, endorse or advertise any
Modified Version, except to acknowledge the contribution(s) of the
Copyright Holder(s) and the Author(s) or with their explicit written
permission.

5) The Font Software, modified or unmodified, in part or in whole,
must be distributed entirely under this license, and must not be
distributed under any other license. The requirement for fonts to
remain under this license does not apply to any document created
using the Font Software.

TERMINATION
This license becomes null and void if any of the above conditions are
not met.

DISCLAIMER
THE FONT SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO ANY WARRANTIES OF
MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT
OF COPYRIGHT, PATENT, TRADEMARK, OR OTHER RIGHT. IN NO EVENT SHALL THE
COPYRIGHT HOLDER BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY,
INCLUDING ANY GENERAL, SPECIAL, INDIRECT, INCIDENTAL, OR CONSEQUENTIAL
DAMAGES, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
FROM, OUT OF THE USE OR INABILITY TO USE THE FONT SOFTWARE OR FROM
OTHER DEALINGS IN THE FONT SOFTWARE.

-->
<!--
Copyright 2020 The JetBrains Mono Project Authors (https://github.com/JetBrains/JetBrainsMono) JetBrainsMono-Italic[wght].ttf: Copyright 2020 The JetBrains Mono Project Authors (https://github.com/JetBrains/JetBrainsMono)

This Font Software is licensed under the SIL Open Font License, Version 1.1.
This license is copied below, and is also available with a FAQ at:
http://scripts.sil.org/OFL


-----------------------------------------------------------
SIL OPEN FONT LICENSE Version 1.1 - 26 February 2007
-----------------------------------------------------------

PREAMBLE
The goals of the Open Font License (OFL) are to stimulate worldwide
development of collaborative font projects, to support the font creation
efforts of academic and linguistic communities, and to provide a free and
open framework in which fonts may be shared and improved in partnership
with others.

The OFL allows the licensed fonts to be used, studied, modified and
redistributed freely as long as they are not sold by themselves. The
fonts, including any derivative works, can be bundled, embedded,
redistributed and/or sold with any software provided that any reserved
names are not used by derivative works. The fonts and derivatives,
however, cannot be released under any other type of license. The
requirement for fonts to remain under this license does not apply
to any document created using the fonts or their derivatives.

DEFINITIONS
"Font Software" refers to the set of files released by the Copyright
Holder(s) under this license and clearly marked as such. This may
include source files, build scripts and documentation.

"Reserved Font Name" refers to any names specified as such after the
copyright statement(s).

"Original Version" refers to the collection of Font Software components as
distributed by the Copyright Holder(s).

"Modified Version" refers to any derivative made by adding to, deleting,
or substituting -- in part or in whole -- any of the components of the
Original Version, by changing formats or by porting the Font Software to a
new environment.

"Author" refers to any designer, engineer, programmer, technical
writer or other person who contributed to the Font Software.

PERMISSION & CONDITIONS
Permission is hereby granted, free of charge, to any person obtaining
a copy of the Font Software, to use, study, copy, merge, embed, modify,
redistribute, and sell modified and unmodified copies of the Font
Software, subject to the following conditions:

1) Neither the Font Software nor any of its individual components,
in Original or Modified Versions, may be sold by itself.

2) Original or Modified Versions of the Font Software may be bundled,
redistributed and/or sold with any software, provided that each copy
contains the above copyright notice and this license. These can be
included either as stand-alone text files, human-readable headers or
in the appropriate machine-readable metadata fields within text or
binary files as long as those fields can be easily viewed by the user.

3) No Modified Version of the Font Software may use the Reserved Font
Name(s) unless explicit written permission is granted by the corresponding
Copyright Holder. This restriction only applies to the primary font name as
presented to the users.

4) The name(s) of the Copyright Holder(s) or the Author(s) of the Font
Software shall not be used to promote, endorse or advertise any
Modified Version, except to acknowledge the contribution(s) of the
Copyright Holder(s) and the Author(s) or with their explicit written
permission.

5) The Font Software, modified or unmodified, in part or in whole,
must be distributed entirely under this license, and must not be
distributed under any other license. The requirement for fonts to
remain under this license does not apply to any document created
using the Font Software.

TERMINATION
This license becomes null and void if any of the above conditions are
not met.

DISCLAIMER
THE FONT SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO ANY WARRANTIES OF
MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT
OF COPYRIGHT, PATENT, TRADEMARK, OR OTHER RIGHT. IN NO EVENT SHALL THE
COPYRIGHT HOLDER BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY,
INCLUDING ANY GENERAL, SPECIAL, INDIRECT, INCIDENTAL, OR CONSEQUENTIAL
DAMAGES, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
FROM, OUT OF THE USE OR INABILITY TO USE THE FONT SOFTWARE OR FROM
OTHER DEALINGS IN THE FONT SOFTWARE.

-->
<!--
Copyright 2020 The Space Grotesk Project Authors (https://github.com/floriankarsten/space-grotesk)

This Font Software is licensed under the SIL Open Font License, Version 1.1.
This license is copied below, and is also available with a FAQ at:
http://scripts.sil.org/OFL


-----------------------------------------------------------
SIL OPEN FONT LICENSE Version 1.1 - 26 February 2007
-----------------------------------------------------------

PREAMBLE
The goals of the Open Font License (OFL) are to stimulate worldwide
development of collaborative font projects, to support the font creation
efforts of academic and linguistic communities, and to provide a free and
open framework in which fonts may be shared and improved in partnership
with others.

The OFL allows the licensed fonts to be used, studied, modified and
redistributed freely as long as they are not sold by themselves. The
fonts, including any derivative works, can be bundled, embedded,
redistributed and/or sold with any software provided that any reserved
names are not used by derivative works. The fonts and derivatives,
however, cannot be released under any other type of license. The
requirement for fonts to remain under this license does not apply
to any document created using the fonts or their derivatives.

DEFINITIONS
"Font Software" refers to the set of files released by the Copyright
Holder(s) under this license and clearly marked as such. This may
include source files, build scripts and documentation.

"Reserved Font Name" refers to any names specified as such after the
copyright statement(s).

"Original Version" refers to the collection of Font Software components as
distributed by the Copyright Holder(s).

"Modified Version" refers to any derivative made by adding to, deleting,
or substituting -- in part or in whole -- any of the components of the
Original Version, by changing formats or by porting the Font Software to a
new environment.

"Author" refers to any designer, engineer, programmer, technical
writer or other person who contributed to the Font Software.

PERMISSION & CONDITIONS
Permission is hereby granted, free of charge, to any person obtaining
a copy of the Font Software, to use, study, copy, merge, embed, modify,
redistribute, and sell modified and unmodified copies of the Font
Software, subject to the following conditions:

1) Neither the Font Software nor any of its individual components,
in Original or Modified Versions, may be sold by itself.

2) Original or Modified Versions of the Font Software may be bundled,
redistributed and/or sold with any software, provided that each copy
contains the above copyright notice and this license. These can be
included either as stand-alone text files, human-readable headers or
in the appropriate machine-readable metadata fields within text or
binary files as long as those fields can be easily viewed by the user.

3) No Modified Version of the Font Software may use the Reserved Font
Name(s) unless explicit written permission is granted by the corresponding
Copyright Holder. This restriction only applies to the primary font name as
presented to the users.

4) The name(s) of the Copyright Holder(s) or the Author(s) of the Font
Software shall not be used to promote, endorse or advertise any
Modified Version, except to acknowledge the contribution(s) of the
Copyright Holder(s) and the Author(s) or with their explicit written
permission.

5) The Font Software, modified or unmodified, in part or in whole,
must be distributed entirely under this license, and must not be
distributed under any other license. The requirement for fonts to
remain under this license does not apply to any document created
using the Font Software.

TERMINATION
This license becomes null and void if any of the above conditions are
not met.

DISCLAIMER
THE FONT SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO ANY WARRANTIES OF
MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT
OF COPYRIGHT, PATENT, TRADEMARK, OR OTHER RIGHT. IN NO EVENT SHALL THE
COPYRIGHT HOLDER BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY,
INCLUDING ANY GENERAL, SPECIAL, INDIRECT, INCIDENTAL, OR CONSEQUENTIAL
DAMAGES, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
FROM, OUT OF THE USE OR INABILITY TO USE THE FONT SOFTWARE OR FROM
OTHER DEALINGS IN THE FONT SOFTWARE.

-->
<script>
!function(n,t){"object"==typeof exports&&"undefined"!=typeof module?t(exports):"function"==typeof define&&define.amd?define(["exports"],t):t((n||self).preact={})}(this,function(n){var t,i,e,r,f,o,u,c,s,a,h,l,p,y,v,d,w="http://www.w3.org/2000/svg",_="http://www.w3.org/1999/xhtml",g=null,m=void 0,b={},k=[],x=/acit|ex(?:s|g|n|p|$)|rph|grid|ows|mnc|ntw|ine[ch]|zoo|^ord|itera/i,M=Array.isArray;function S(n,t){for(var i in t)n[i]=t[i];return n}function T(n){n&&n.parentNode&&n.parentNode.removeChild(n)}function $(n,i,e){var r,f,o,u={};for(o in i)"key"==o?r=i[o]:"ref"==o?f=i[o]:u[o]=i[o];if(arguments.length>2&&(u.children=arguments.length>3?t.call(arguments,2):e),"function"==typeof n&&n.defaultProps!=g)for(o in n.defaultProps)u[o]===m&&(u[o]=n.defaultProps[o]);return C(n,u,r,f,g)}function C(n,t,r,f,o){var u={type:n,props:t,key:r,ref:f,__k:g,__:g,__b:0,__e:g,__c:g,constructor:m,__v:o==g?++e:o,__i:-1,__u:0};return o==g&&i.vnode!=g&&i.vnode(u),u}function I(n){return n.children}function P(n,t){this.props=n,this.context=t}function j(n,t){if(t==g)return n.__?j(n.__,n.__i+1):g;for(var i;t<n.__k.length;t++)if((i=n.__k[t])!=g&&i.__e!=g)return i.__e;return"function"==typeof n.type?j(n):g}function A(n){if(n.__P&&n.__d){var t=n.__v,e=t.__e,r=[],f=[],o=S({},t);o.__v=t.__v+1,i.vnode&&i.vnode(o),E(n.__P,o,t,n.__n,n.__P.namespaceURI,32&t.__u?[e]:g,r,e==g?j(t):e,!!(32&t.__u),f),o.__v=t.__v,o.__.__k[o.__i]=o,J(r,o,f),t.__e=t.__=null,o.__e!=e&&H(o)}}function H(n){if((n=n.__)!=g&&n.__c!=g)return n.__e=n.__c.base=g,n.__k.some(function(t){if(t!=g&&t.__e!=g)return n.__e=n.__c.base=t.__e}),H(n)}function L(n){(!n.__d&&(n.__d=!0)&&f.push(n)&&!F.__r++||o!=i.debounceRendering)&&((o=i.debounceRendering)||u)(F)}function F(){try{for(var n,t=1;f.length;)f.length>t&&f.sort(c),n=f.shift(),t=f.length,A(n)}finally{f.length=F.__r=0}}function O(n,t,i,e,r,f,o,u,c,s,a){var h,l,p,y,v,d,w=e&&e.__k||k,_=t.length;for(c=z(i,t,w,c,_),h=0;h<_;h++)(p=i.__k[h])!=g&&(l=-1!=p.__i&&w[p.__i]||b,p.__i=h,d=E(n,p,l,r,f,o,u,c,s,a),y=p.__e,p.ref&&l.ref!=p.ref&&(l.ref&&R(l.ref,g,p),a.push(p.ref,p.__c||y,p)),v==g&&y!=g&&(v=y),4&p.__u?(c=N(p,c,n),l.__e&&(l.__e=g)):"function"==typeof p.type&&d!==m?c=d:y&&(c=y.nextSibling),p.__u&=-7);return i.__e=v,c}function z(n,t,i,e,r){var f,o,u,c,s,a=i.length,h=a,l=0;for(n.__k=new Array(r),f=0;f<r;f++)(o=t[f])!=g&&"boolean"!=typeof o&&"function"!=typeof o?("string"==typeof o||"number"==typeof o||"bigint"==typeof o||o.constructor==String?o=n.__k[f]=C(g,o,g,g,g):M(o)?o=n.__k[f]=C(I,{children:o},g,g,g):o.constructor===m&&o.__b>0?o=n.__k[f]=C(o.type,o.props,o.key,o.ref?o.ref:g,o.__v):n.__k[f]=o,c=f+l,o.__=n,o.__b=n.__b+1,s=o.__i=V(o,i,c,h),u=g,-1!=s&&(h--,(u=i[s])&&(u.__u|=2)),u==g||u.__v==g?(-1==s&&(r>a?l--:r<a&&l++),"function"!=typeof o.type&&(o.__u|=4)):s!=c&&(s==c-1?l--:s==c+1?l++:(s>c?l--:l++,o.__u|=4))):n.__k[f]=g;if(h)for(f=0;f<a;f++)(u=i[f])!=g&&0==(2&u.__u)&&(u.__e==e&&(e=j(u)),U(u,u));return e}function N(n,t,i){var e,r;if("function"==typeof n.type){for(e=n.__k,r=0;e&&r<e.length;r++)e[r]&&(e[r].__=n,t=N(e[r],t,i));return t}n.__e!=t&&(t&&n.type&&!t.parentNode&&(t=j(n)),t=i.insertBefore(n.__e,t||g));do{t=t&&t.nextSibling}while(t!=g&&8==t.nodeType);return t}function V(n,t,i,e){var r,f,o,u=n.key,c=n.type,s=t[i],a=s!=g&&0==(2&s.__u);if(s===g&&null==u||a&&u==s.key&&c==s.type)return i;if(e>(a?1:0))for(r=i-1,f=i+1;r>=0||f<t.length;)if((s=t[o=r>=0?r--:f++])!=g&&0==(2&s.__u)&&u==s.key&&c==s.type)return o;return-1}function q(n,t,i){"-"==t[0]?n.setProperty(t,i==g?"":i):n[t]=i==g?"":"number"!=typeof i||x.test(t)?i:i+"px"}function B(n,t,i,e,r){var f,o;n:if("style"==t)if("string"==typeof i)n.style.cssText=i;else{if("string"==typeof e&&(n.style.cssText=e=""),e)for(t in e)i&&t in i||q(n.style,t,"");if(i)for(t in i)e&&i[t]==e[t]||q(n.style,t,i[t])}else if("o"==t[0]&&"n"==t[1])f=t!=(t=t.replace(l,"$1")),o=t.toLowerCase(),t=o in n||"onFocusOut"==t||"onFocusIn"==t?o.slice(2):t.slice(2),n.l||(n.l={}),n.l[t+f]=i,i?e?i[h]=e[h]:(i[h]=p,n.addEventListener(t,f?v:y,f)):n.removeEventListener(t,f?v:y,f);else{if(r==w)t=t.replace(/xlink(H|:h)/,"h").replace(/sName$/,"s");else if("width"!=t&&"height"!=t&&"href"!=t&&"list"!=t&&"form"!=t&&"tabIndex"!=t&&"download"!=t&&"rowSpan"!=t&&"colSpan"!=t&&"role"!=t&&"popover"!=t&&t in n)try{n[t]=i==g?"":i;break n}catch(n){}"function"==typeof i||(i==g||!1===i&&"-"!=t[4]?n.removeAttribute(t):n.setAttribute(t,"popover"==t&&1==i?"":i))}}function D(n){return function(t){if(this.l){var e=this.l[t.type+n];if(t[a]==g)t[a]=p++;else if(t[a]<e[h])return;return e(i.event?i.event(t):t)}}}function E(n,t,e,r,f,o,u,c,s,a){var h,l,p,y,v,d,w,_,b,x,$,C,A,H,L,F,z=t.type;if(t.constructor!==m)return g;128&e.__u&&(s=!!(32&e.__u),o=[c=t.__e=e.__e]),(h=i.__b)&&h(t);n:if("function"==typeof z){l=u.length;try{if(b=t.props,x=z.prototype&&z.prototype.render,$=(h=z.contextType)&&r[h.__c],C=h?$?$.props.value:h.__:r,e.__c?_=(p=t.__c=e.__c).__=p.__E:(x?t.__c=p=new z(b,C):(t.__c=p=new P(b,C),p.constructor=z,p.render=W),$&&$.sub(p),p.state||(p.state={}),p.__n=r,y=p.__d=!0,p.__h=[],p._sb=[]),x&&p.__s==g&&(p.__s=p.state),x&&z.getDerivedStateFromProps!=g&&(p.__s==p.state&&(p.__s=S({},p.__s)),S(p.__s,z.getDerivedStateFromProps(b,p.__s))),v=p.props,d=p.state,p.__v=t,y)x&&z.getDerivedStateFromProps==g&&p.componentWillMount!=g&&p.componentWillMount(),x&&p.componentDidMount!=g&&p.__h.push(p.componentDidMount);else{if(x&&z.getDerivedStateFromProps==g&&b!==v&&p.componentWillReceiveProps!=g&&p.componentWillReceiveProps(b,C),t.__v==e.__v||!p.__e&&p.shouldComponentUpdate!=g&&!1===p.shouldComponentUpdate(b,p.__s,C)){t.__v!=e.__v&&(p.props=b,p.state=p.__s,p.__d=!1),t.__e=e.__e,t.__k=e.__k,t.__k.some(function(n){n&&(n.__=t)}),k.push.apply(p.__h,p._sb),p._sb=[],p.__h.length&&u.push(p),c=j(e);break n}p.componentWillUpdate!=g&&p.componentWillUpdate(b,p.__s,C),x&&p.componentDidUpdate!=g&&p.__h.push(function(){p.componentDidUpdate(v,d,w)})}if(p.context=C,p.props=b,p.__P=n,p.__e=!1,A=i.__r,H=0,x)p.state=p.__s,p.__d=!1,A&&A(t),h=p.render(p.props,p.state,p.context),k.push.apply(p.__h,p._sb),p._sb=[];else do{p.__d=!1,A&&A(t),h=p.render(p.props,p.state,p.context),p.state=p.__s}while(p.__d&&++H<25);p.state=p.__s,p.getChildContext!=g&&(r=S(S({},r),p.getChildContext())),x&&!y&&p.getSnapshotBeforeUpdate!=g&&(w=p.getSnapshotBeforeUpdate(v,d)),L=h!=g&&h.type===I&&h.key==g?K(h.props.children):h,c=O(n,M(L)?L:[L],t,e,r,f,o,u,c,s,a),p.base=t.__e,t.__u&=-161,p.__h.length&&u.push(p),_&&(p.__E=p.__=g)}catch(n){if(u.length=l,t.__v=g,s||o!=g){if(n.then){for(t.__u|=s?160:128;c&&8==c.nodeType&&c.nextSibling;)c=c.nextSibling;o!=g&&(o[o.indexOf(c)]=g),t.__e=c}else if(o!=g)for(F=o.length;F--;)T(o[F])}else t.__e=e.__e;t.__k==g&&(t.__k=e.__k||[]),n.then||G(t),i.__e(n,t,e)}}else o==g&&t.__v==e.__v?(t.__k=e.__k,t.__e=e.__e):c=t.__e=Q(e.__e,t,e,r,f,o,u,s,a);return(h=i.diffed)&&h(t),128&t.__u?void 0:c}function G(n){n&&(n.__c&&(n.__c.__e=!0),n.__k&&n.__k.some(G))}function J(n,t,e){for(var r=0;r<e.length;r++)R(e[r],e[++r],e[++r]);i.__c&&i.__c(t,n),n.some(function(t){try{n=t.__h,t.__h=[],n.some(function(n){n.call(t)})}catch(n){i.__e(n,t.__v)}})}function K(n){return"object"!=typeof n||n==g||n.__b>0?n:M(n)?n.map(K):n.constructor!==m?null:S({},n)}function Q(n,e,r,f,o,u,c,s,a){var h,l,p,y,v,d,k,x=r.props||b,S=e.props,$=e.type;if("svg"==$?o=w:"math"==$?o="http://www.w3.org/1998/Math/MathML":o||(o=_),u!=g)for(h=0;h<u.length;h++)if((v=u[h])&&"setAttribute"in v==!!$&&($?v.localName==$:3==v.nodeType)){n=v,u[h]=g;break}if(n==g){if($==g)return document.createTextNode(S);n=document.createElementNS(o,$,S.is&&S),s&&(i.__m&&i.__m(e,u),s=!1),u=g}if($==g)x===S||s&&n.data==S||(n.data=S);else{if(u="textarea"==$&&S.defaultValue!=g?g:u&&t.call(n.childNodes),!s&&u!=g)for(x={},h=0;h<n.attributes.length;h++)x[(v=n.attributes[h]).name]=v.value;for(h in x)v=x[h],"dangerouslySetInnerHTML"==h?p=v:"children"==h||h in S||"value"==h&&"defaultValue"in S||"checked"==h&&"defaultChecked"in S||B(n,h,g,v,o);for(h in S)v=S[h],"children"==h?y=v:"dangerouslySetInnerHTML"==h?l=v:"value"==h?d=v:"checked"==h?k=v:s&&"function"!=typeof v||x[h]===v||B(n,h,v,x[h],o);if(l)s||p&&(l.__html==p.__html||l.__html==n.innerHTML)||(n.innerHTML=l.__html),e.__k=[];else if(p&&(n.innerHTML=""),O("template"==e.type?n.content:n,M(y)?y:[y],e,r,f,"foreignObject"==$?_:o,u,c,u?u[0]:r.__k&&j(r,0),s,a),u!=g)for(h=u.length;h--;)T(u[h]);s&&"textarea"!=$||(h="value","progress"==$&&d==g?n.removeAttribute("value"):d!=m&&(d!==n[h]||"progress"==$&&!d||"option"==$&&d!=x[h])&&B(n,h,d,x[h],o),h="checked",k!=m&&k!=n[h]&&B(n,h,k,x[h],o))}return n}function R(n,t,e){try{if("function"==typeof n){var r="function"==typeof n.__u;r&&n.__u(),r&&t==g||(n.__u=n(t))}else n.current=t}catch(n){i.__e(n,e)}}function U(n,t,e){var r,f;if(i.unmount&&i.unmount(n),(r=n.ref)&&(r.current&&r.current!=n.__e||R(r,g,t)),(r=n.__c)!=g){if(r.componentWillUnmount)try{r.componentWillUnmount()}catch(n){i.__e(n,t)}r.base=r.__P=r.__n=g}if(r=n.__k)for(f=0;f<r.length;f++)r[f]&&U(r[f],t,e||"function"!=typeof n.type);e||T(n.__e),n.__c=n.__=n.__e=m}function W(n,t,i){return this.constructor(n,i)}function X(n,e,r){var f,o,u,c;e==document&&(e=document.documentElement),i.__&&i.__(n,e),o=(f="function"==typeof r)?g:r&&r.__k||e.__k,u=[],c=[],E(e,n=(!f&&r||e).__k=$(I,g,[n]),o||b,b,e.namespaceURI,!f&&r?[r]:o?g:e.firstChild?t.call(e.childNodes):g,u,!f&&r?r:o?o.__e:e.firstChild,f,c),J(u,n,c),n.props.children=g}t=k.slice,i={__e:function(n,t,i,e){for(var r,f,o;t=t.__;)if((r=t.__c)&&!r.__)try{if((f=r.constructor)&&f.getDerivedStateFromError!=g&&(r.setState(f.getDerivedStateFromError(n)),o=r.__d),r.componentDidCatch!=g&&(r.componentDidCatch(n,e||{}),o=r.__d),o)return r.__E=r}catch(t){n=t}throw n}},e=0,r=function(n){return n!=g&&n.constructor===m},P.prototype.setState=function(n,t){var i;i=this.__s!=g&&this.__s!=this.state?this.__s:this.__s=S({},this.state),"function"==typeof n&&(n=n(S({},i),this.props)),n&&S(i,n),n!=g&&this.__v&&(t&&this._sb.push(t),L(this))},P.prototype.forceUpdate=function(n){this.__v&&(this.__e=!0,n&&this.__h.push(n),L(this))},P.prototype.render=I,f=[],u="function"==typeof Promise?Promise.prototype.then.bind(Promise.resolve()):setTimeout,c=function(n,t){return n.__v.__b-t.__v.__b},F.__r=0,s=Math.random().toString(8),a="__d"+s,h="__a"+s,l=/(PointerCapture)$|Capture$/i,p=0,y=D(!1),v=D(!0),d=0,n.Component=P,n.Fragment=I,n.cloneElement=function(n,i,e){var r,f,o,u,c=S({},n.props);for(o in n.type&&n.type.defaultProps&&(u=n.type.defaultProps),i)"key"==o?r=i[o]:"ref"==o?f=i[o]:c[o]=i[o]===m&&u!=m?u[o]:i[o];return arguments.length>2&&(c.children=arguments.length>3?t.call(arguments,2):e),C(n.type,c,r||n.key,f||n.ref,g)},n.createContext=function(n){function t(n){var i,e;return this.getChildContext||(i=new Set,(e={})[t.__c]=this,this.getChildContext=function(){return e},this.componentWillUnmount=function(){i=g},this.shouldComponentUpdate=function(n){this.props.value!=n.value&&i.forEach(function(n){n.__e=!0,L(n)})},this.sub=function(n){i.add(n);var t=n.componentWillUnmount;n.componentWillUnmount=function(){i&&i.delete(n),t&&t.call(n)}}),n.children}return t.__c="__cC"+d++,t.__=n,t.Provider=t.__l=(t.Consumer=function(n,t){return n.children(t)}).contextType=t,t},n.createElement=$,n.createRef=function(){return{current:g}},n.h=$,n.hydrate=function n(t,i){X(t,i,n)},n.isValidElement=r,n.options=i,n.render=X,n.toChildArray=function n(t,i){return i=i||[],t==g||"boolean"==typeof t||(M(t)?t.some(function(t){n(t,i)}):i.push(t)),i}});
//# sourceMappingURL=preact.umd.js.map

</script>
<script>
!function(n,t){"object"==typeof exports&&"undefined"!=typeof module?t(exports,require("preact")):"function"==typeof define&&define.amd?define(["exports","preact"],t):t((n||self).preactHooks={},n.preact)}(this,function(n,t){var u,i,r,o,f=0,c=[],e=t.options,a=e.__b,v=e.__r,l=e.diffed,d=e.__c,p=e.unmount,s=e.__;function y(n,t){e.__h&&e.__h(i,n,f||t),f=0;var u=i.__H||(i.__H={__:[],__h:[]});return n>=u.__.length&&u.__.push({}),u.__[n]}function h(n){return f=1,m(j,n)}function m(n,t,r){var o=y(u++,2);if(o.t=n,!o.__c&&(o.__=[r?r(t):j(void 0,t),function(n){var t=o.__N?o.__N[0]:o.__[0],u=o.t(t,n);t!==u&&(o.__N=[u,o.__[1]],o.__c.setState({}))}],o.__c=i,!i.__f)){var f=function(n,t,u){if(!o.__c.__H)return!0;var i=!1,r=o.__c.props!==n;if(o.__c.__H.__.some(function(n){if(n.__N){i=!0;var t=n.__[0];n.__=n.__N,n.__N=void 0,t!==n.__[0]&&(r=!0)}}),c){var f=c.call(this,n,t,u);return i?f||r:f}return!i||r};i.__f=!0;var c=i.shouldComponentUpdate,e=i.componentWillUpdate;i.componentWillUpdate=function(n,t,u){if(this.__e){var i=c;c=void 0,f(n,t,u),c=i}e&&e.call(this,n,t,u)},i.shouldComponentUpdate=f}return o.__N||o.__}function T(n,t){var r=y(u++,4);!e.__s&&g(r.__H,t)&&(r.__=n,r.u=t,i.__h.push(r))}function _(n,t){var i=y(u++,7);return g(i.__H,t)&&(i.__=n(),i.__H=t,i.__h=n),i.__}function b(){for(var n;n=c.shift();){var t=n.__H;if(n.__P&&t)try{t.__h.some(A),t.__h.some(F),t.__h=[]}catch(u){t.__h=[],e.__e(u,n.__v)}}}e.__b=function(n){i=null,a&&a(n)},e.__=function(n,t){n&&t.__k&&t.__k.__m&&(n.__m=t.__k.__m),s&&s(n,t)},e.__r=function(n){v&&v(n),u=0;var t=(i=n.__c).__H;t&&(r===i?(t.__h=[],i.__h=[],t.__.some(function(n){n.__N&&(n.__=n.__N),n.u=n.__N=void 0})):(t.__h.some(A),t.__h.some(F),t.__h=[],u=0)),r=i},e.diffed=function(n){l&&l(n);var t=n.__c;t&&t.__H&&(t.__H.__h.length&&(1!==c.push(t)&&o===e.requestAnimationFrame||((o=e.requestAnimationFrame)||x)(b)),t.__H.__.some(function(n){n.u&&(n.__H=n.u,n.u=void 0)})),r=i=null},e.__c=function(n,t){t.some(function(n){try{n.__h.some(A),n.__h=n.__h.filter(function(n){return!n.__||F(n)})}catch(u){t.some(function(n){n.__h&&(n.__h=[])}),t=[],e.__e(u,n.__v)}}),d&&d(n,t)},e.unmount=function(n){p&&p(n);var t,u=n.__c;u&&u.__H&&(u.__H.__.some(function(n){try{A(n)}catch(n){t=n}}),u.__H=void 0,t&&e.__e(t,u.__v))};var q="function"==typeof requestAnimationFrame;function x(n){var t,u=function(){clearTimeout(i),q&&cancelAnimationFrame(t),setTimeout(n)},i=setTimeout(u,35);q&&(t=requestAnimationFrame(u))}function A(n){var t=i,u=n.__c;"function"==typeof u&&(n.__c=void 0,u()),i=t}function F(n){var t=i;n.__c=n.__(),i=t}function g(n,t){return!n||n.length!==t.length||t.some(function(t,u){return t!==n[u]})}function j(n,t){return"function"==typeof t?t(n):t}n.useCallback=function(n,t){return f=8,_(function(){return n},t)},n.useContext=function(n){var t=i.context[n.__c],r=y(u++,9);return r.c=n,t?(null==r.__&&(r.__=!0,t.sub(i)),t.props.value):n.__},n.useDebugValue=function(n,t){e.useDebugValue&&e.useDebugValue(t?t(n):n)},n.useEffect=function(n,t){var r=y(u++,3);!e.__s&&g(r.__H,t)&&(r.__=n,r.u=t,i.__H.__h.push(r))},n.useErrorBoundary=function(n){var t=y(u++,10),r=h();return t.__=n,i.componentDidCatch||(i.componentDidCatch=function(n,u){t.__&&t.__(n,u),r[1](n)}),[r[0],function(){r[1](void 0)}]},n.useId=function(){var n=y(u++,11);if(!n.__){for(var t=i.__v;null!==t&&!t.__m&&null!==t.__;)t=t.__;var r=t.__m||(t.__m=[0,0]);n.__="P"+r[0]+"-"+r[1]++}return n.__},n.useImperativeHandle=function(n,t,u){f=6,T(function(){if("function"==typeof n){var u=n(t());return function(){n(null),u&&"function"==typeof u&&u()}}if(n)return n.current=t(),function(){return n.current=null}},null==u?u:u.concat(n))},n.useLayoutEffect=T,n.useMemo=_,n.useReducer=m,n.useRef=function(n){return f=5,_(function(){return{current:n}},[])},n.useState=h});
//# sourceMappingURL=hooks.umd.js.map

</script>
<script>
!function(n,e){"object"==typeof exports&&"undefined"!=typeof module?module.exports=e():"function"==typeof define&&define.amd?define(e):n.htm=e()}(this,function(){var n=function(e,t,u,s){var r;t[0]=0;for(var p=1;p<t.length;p++){var h=t[p++],o=t[p]?(t[0]|=h?1:2,u[t[p++]]):t[++p];3===h?s[0]=o:4===h?s[1]=Object.assign(s[1]||{},o):5===h?(s[1]=s[1]||{})[t[++p]]=o:6===h?s[1][t[++p]]+=o+"":h?(r=e.apply(o,n(e,o,u,["",null])),s.push(r),o[0]?t[0]|=2:(t[p-2]=0,t[p]=r)):s.push(o)}return s},e=new Map;return function(t){var u=e.get(this);return u||(u=new Map,e.set(this,u)),(u=n(this,u.get(t)||(u.set(t,u=function(n){for(var e,t,u=1,s="",r="",p=[0],h=function(n){1===u&&(n||(s=s.replace(/^\s*\n\s*|\s*\n\s*$/g,"")))?p.push(0,n,s):3===u&&(n||s)?(p.push(3,n,s),u=2):2===u&&"..."===s&&n?p.push(4,n,0):2===u&&s&&!n?p.push(5,0,!0,s):u>=5&&((s||!n&&5===u)&&(p.push(u,0,s,t),u=6),n&&(p.push(u,n,0,t),u=6)),s=""},o=0;o<n.length;o++){o&&(1===u&&h(),h(o));for(var f=0;f<n[o].length;f++)e=n[o][f],1===u?"<"===e?(h(),p=[p],u=3):s+=e:4===u?"--"===s&&">"===e?(u=1,s=""):s=e+s[0]:r?e===r?r="":s+=e:'"'===e||"'"===e?r=e:">"===e?(h(),u=1):u&&("="===e?(u=5,t=s,s=""):"/"===e&&(u<5||">"===n[o][f+1])?(h(),3===u&&(p=p[0]),u=p,(p=p[0]).push(2,0,u),u=0):" "===e||"\t"===e||"\n"===e||"\r"===e?(h(),u=2):s+=e),3===u&&"!--"===s&&(u=4,p=p[0])}return h(),p}(t)),u),arguments,[])).length>1?u:u[0]}});

</script>
<script>window.lucideIcons={"ArrowLeft":[["path",{"d":"m12 19-7-7 7-7"}],["path",{"d":"M19 12H5"}]],"FileText":[["path",{"d":"M6 22a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h8a2.4 2.4 0 0 1 1.704.706l3.588 3.588A2.4 2.4 0 0 1 20 8v12a2 2 0 0 1-2 2z"}],["path",{"d":"M14 2v5a1 1 0 0 0 1 1h5"}],["path",{"d":"M10 9H8"}],["path",{"d":"M16 13H8"}],["path",{"d":"M16 17H8"}]],"FolderOpen":[["path",{"d":"m6 14 1.5-2.9A2 2 0 0 1 9.24 10H20a2 2 0 0 1 1.94 2.5l-1.54 6a2 2 0 0 1-1.95 1.5H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h3.9a2 2 0 0 1 1.69.9l.81 1.2a2 2 0 0 0 1.67.9H18a2 2 0 0 1 2 2v2"}]],"GitBranch":[["path",{"d":"M15 6a9 9 0 0 0-9 9V3"}],["circle",{"cx":"18","cy":"6","r":"3"}],["circle",{"cx":"6","cy":"18","r":"3"}]],"Inbox":[["polyline",{"points":"22 12 16 12 14 15 10 15 8 12 2 12"}],["path",{"d":"M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z"}]],"Link":[["path",{"d":"M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"}],["path",{"d":"M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"}]],"Loader":[["path",{"d":"M12 2v4"}],["path",{"d":"m16.2 7.8 2.9-2.9"}],["path",{"d":"M18 12h4"}],["path",{"d":"m16.2 16.2 2.9 2.9"}],["path",{"d":"M12 18v4"}],["path",{"d":"m4.9 19.1 2.9-2.9"}],["path",{"d":"M2 12h4"}],["path",{"d":"m4.9 4.9 2.9 2.9"}]],"RefreshCw":[["path",{"d":"M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8"}],["path",{"d":"M21 3v5h-5"}],["path",{"d":"M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16"}],["path",{"d":"M8 16H3v5"}]],"Settings":[["path",{"d":"M9.671 4.136a2.34 2.34 0 0 1 4.659 0 2.34 2.34 0 0 0 3.319 1.915 2.34 2.34 0 0 1 2.33 4.033 2.34 2.34 0 0 0 0 3.831 2.34 2.34 0 0 1-2.33 4.033 2.34 2.34 0 0 0-3.319 1.915 2.34 2.34 0 0 1-4.659 0 2.34 2.34 0 0 0-3.32-1.915 2.34 2.34 0 0 1-2.33-4.033 2.34 2.34 0 0 0 0-3.831A2.34 2.34 0 0 1 6.35 6.051a2.34 2.34 0 0 0 3.319-1.915"}],["circle",{"cx":"12","cy":"12","r":"3"}]],"Shield":[["path",{"d":"M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z"}]],"Trash2":[["path",{"d":"M10 11v6"}],["path",{"d":"M14 11v6"}],["path",{"d":"M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"}],["path",{"d":"M3 6h18"}],["path",{"d":"M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"}]],"CheckCircle":[["path",{"d":"M21.801 10A10 10 0 1 1 17 3.335"}],["path",{"d":"m9 11 3 3L22 4"}]],"Edit":[["path",{"d":"M12 3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"}],["path",{"d":"M18.375 2.625a1 1 0 0 1 3 3l-9.013 9.014a2 2 0 0 1-.853.505l-2.873.84a.5.5 0 0 1-.62-.62l.84-2.873a2 2 0 0 1 .506-.852z"}]],"Eye":[["path",{"d":"M2.062 12.348a1 1 0 0 1 0-.696 10.75 10.75 0 0 1 19.876 0 1 1 0 0 1 0 .696 10.75 10.75 0 0 1-19.876 0"}],["circle",{"cx":"12","cy":"12","r":"3"}]]};</script>
<script>
(function () {
  const { h, render, Component } = window.preact;
  const { useMemo, useLayoutEffect } = window.preactHooks;
  function Icon({ name, size = 16, strokeWidth = 2, ...rest }) {
    const nodes = Object.hasOwn(window.lucideIcons || {}, name) ? window.lucideIcons[name] : null;
    if (!nodes) { console.error(`Unknown Lucide icon: ${name}`); return null; }
    return h('svg', { xmlns: 'http://www.w3.org/2000/svg', width: size, height: size,
      viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor',
      'stroke-width': strokeWidth, 'stroke-linecap': 'round', 'stroke-linejoin': 'round', ...rest },
      nodes.map(([tag, attrs]) => h(tag, attrs)));
  }
  function Portal({ children }) {
    const host = useMemo(() => document.createElement('div'), []);
    useLayoutEffect(() => {
      document.body.appendChild(host);
      return () => { render(null, host); host.remove(); };
    }, [host]);
    useLayoutEffect(() => { render(children, host); }, [children, host]);
    return null;
  }
  function shallowEqual(a, b) {
    const keys = Object.keys(a);
    return keys.length === Object.keys(b).length && keys.every(key => Object.is(a[key], b[key]));
  }
  function memo(Inner, areEqual = shallowEqual) {
    return class extends Component {
      shouldComponentUpdate(next) { return !areEqual(this.props, next); }
      render(props) { return h(Inner, props); }
    };
  }
  function focusOnMount(element) { if (element) element.focus(); }
  window.frontendKit = { Icon, Portal, memo, focusOnMount };
})();

</script>
<style>@font-face{font-family:"DM Sans";font-style:normal;font-weight:100 1000;src:url(data:font/woff2;base64,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) format('woff2');}</style>
<style>@font-face{font-family:"JetBrains Mono";font-style:normal;font-weight:100 800;src:url(data:font/woff2;base64,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) format('woff2');}</style>
<style>@font-face{font-family:"Space Grotesk";font-style:normal;font-weight:300 700;src:url(data:font/woff2;base64,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) format('woff2');}</style>"""
# frontend-vendor:end


DESIGN_TOKENS_BLOCK = """
:root {
  /* === Background === */
  --bg-base: #0f1117;           /* Main page background - very dark blue-gray */
  --bg-surface: #161922;        /* Card/panel backgrounds */
  --bg-surface-raised: #1c1f2e; /* Elevated surfaces (modals, dropdowns) */
  --bg-surface-hover: #232738;  /* Hover state on interactive surfaces */
  --bg-input: #0c0e14;          /* Input field backgrounds */
  --bg-log: #0a0c10;            /* Log viewer background (darkest) */

  /* === Text === */
  --text-primary: #e8eaed;      /* Primary text - slightly warm white */
  --text-secondary: #8b8fa3;    /* Secondary/dimmed text */
  --text-muted: #4a4e63;        /* Very dimmed text (idle labels, timestamps) */
  --text-inverse: #0f1117;      /* Text on bright backgrounds */

  /* === Status Colors === */
  --status-done: #34d399;       /* Green - completed/healthy */
  --status-active: #f59e0b;     /* Amber - in progress */
  --status-ready: #3b82f6;      /* Blue - queued/ready */
  --status-blocked: #ef4444;    /* Red - error/blocked */
  --status-staged: #a78bfa;     /* Purple - staged/planning */
  --status-idle: #374151;       /* Dark gray - idle/inactive */
  --status-review: #f97316;     /* Orange - needs human review */

  /* === Status Glows (for box-shadow) === */
  --glow-done: rgba(52, 211, 153, 0.15);
  --glow-active: rgba(245, 158, 11, 0.15);
  --glow-blocked: rgba(239, 68, 68, 0.25);
  --glow-ready: rgba(59, 130, 246, 0.1);

  /* === Borders === */
  --border-subtle: #1e2231;     /* Default card/panel borders */
  --border-medium: #2a2f42;     /* Stronger separation */
  --border-focus: #3b82f6;      /* Focus ring color */

  /* === Typography === */
  --font-display: 'Space Grotesk', 'DM Sans', sans-serif;    /* Headers, labels */
  --font-mono: 'JetBrains Mono', 'IBM Plex Mono', monospace; /* Data, logs, IDs */
  --font-body: 'DM Sans', 'Space Grotesk', sans-serif;       /* Body text */

  /* === Font Sizes === */
  --text-xs: 0.6875rem;    /* 11px - timestamps, fine print */
  --text-sm: 0.75rem;      /* 12px - secondary labels */
  --text-base: 0.8125rem;  /* 13px - body text (dense UI) */
  --text-md: 0.875rem;     /* 14px - primary labels */
  --text-lg: 1rem;         /* 16px - section headers */
  --text-xl: 1.25rem;      /* 20px - page headers */
  --text-2xl: 1.5rem;      /* 24px - view titles */

  /* === Spacing === */
  --space-1: 4px;
  --space-2: 8px;
  --space-3: 12px;
  --space-4: 16px;
  --space-5: 20px;
  --space-6: 24px;
  --space-8: 32px;

  /* === Border Radius === */
  --radius-sm: 4px;
  --radius-md: 6px;
  --radius-lg: 8px;
  --radius-xl: 12px;

  /* === Transitions === */
  --transition-fast: 150ms ease;
  --transition-base: 250ms ease;
  --transition-slow: 400ms ease;

  /* === Z-index layers === */
  --z-base: 0;
  --z-cards: 10;
  --z-sticky: 20;
  --z-overlay: 30;
  --z-modal: 40;
  --z-tooltip: 50;

  /* === Layout === */
  --topbar-height: 48px;
  --pipeline-strip-height: 44px;
  --worker-card-min-height: 220px;
  --log-tail-lines: 5;          /* Number of visible lines in worker card log tail */
  --sidebar-width: 280px;       /* For views that use sidebar layout */
}
""".strip()


def render_app_html(bootstrap: dict[str, Any]) -> str:
    template = dedent(
        """\
        <!DOCTYPE html>
        <html lang="en">
          <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1">
            <title>Cognitive Switchyard</title>
            <!-- frontend-vendor -->
            <style>
              __DESIGN_TOKENS_BLOCK__

              * {
                box-sizing: border-box;
              }

              html {
                line-height: 1.5;
              }

              html, body {
                margin: 0;
                min-height: 100%;
              }

              h1, h2, h3, h4, h5, h6, p {
                margin: 0;
              }

              h1, h2, h3, h4, h5, h6 {
                font-size: inherit;
                font-weight: inherit;
              }

              svg {
                display: block;
                vertical-align: middle;
              }

              body {
                font-family: var(--font-body);
                color: var(--text-primary);
                background-color: var(--bg-base);
                background-image:
                  radial-gradient(ellipse at 20% 50%, rgba(59, 130, 246, 0.03) 0%, transparent 50%),
                  radial-gradient(ellipse at 80% 20%, rgba(139, 92, 246, 0.02) 0%, transparent 40%);
              }

              body::before {
                content: "";
                position: fixed;
                inset: 0;
                opacity: 0.025;
                background-image: url("data:image/svg+xml,%3Csvg viewBox='0 0 256 256' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)'/%3E%3C/svg%3E");
                pointer-events: none;
                z-index: -1;
              }

              @keyframes pulse-active {
                0%, 100% { box-shadow: 0 0 0 1px var(--status-active), 0 0 8px var(--glow-active); }
                50% { box-shadow: 0 0 0 1px var(--status-active), 0 0 16px var(--glow-active); }
              }

              @keyframes pulse-error {
                0%, 100% { box-shadow: 0 0 0 2px var(--status-blocked), 0 0 12px var(--glow-blocked); }
                50% { box-shadow: 0 0 0 2px var(--status-blocked), 0 0 24px var(--glow-blocked); }
              }

              @keyframes breathe {
                0%, 100% { opacity: 0.4; }
                50% { opacity: 0.6; }
              }

              @keyframes log-slide-in {
                from { opacity: 0; transform: translateY(4px); }
                to { opacity: 1; transform: translateY(0); }
              }

              @keyframes count-bump {
                0% { transform: scale(1); }
                50% { transform: scale(1.15); }
                100% { transform: scale(1); }
              }

              @keyframes fade-in-up {
                from { opacity: 0; transform: translateY(8px); }
                to { opacity: 1; transform: translateY(0); }
              }

              @keyframes segment-fill {
                from { width: 0%; }
                to { width: 100%; }
              }

              a {
                color: inherit;
                text-decoration: none;
              }

              button, input, select, textarea {
                font: inherit;
              }

              #switchyard-app {
                min-height: 100vh;
              }

              .app-shell {
                min-height: 100vh;
              }

              .topbar {
                position: sticky;
                top: 0;
                z-index: var(--z-sticky);
                min-height: var(--topbar-height);
                display: flex;
                align-items: center;
                justify-content: space-between;
                gap: var(--space-4);
                padding: 0 var(--space-4);
                background: rgba(22, 25, 34, 0.92);
                backdrop-filter: blur(12px);
                border-bottom: 1px solid var(--border-subtle);
                animation: fade-in-up 400ms ease forwards;
              }

              .brand {
                font-family: var(--font-display);
                font-size: var(--text-md);
                font-weight: 700;
                letter-spacing: 0.08em;
                text-transform: uppercase;
              }

              .topbar-center,
              .topbar-nav,
              .row,
              .action-row {
                display: flex;
                align-items: center;
                gap: var(--space-3);
              }

              .topbar-center {
                flex: 1;
                min-width: 0;
              }

              .topbar-nav {
                flex-wrap: wrap;
                justify-content: flex-end;
              }

              .session-text,
              .mono,
              .log-panel,
              .log-tail,
              .intake-list,
              .stage-badge,
              .status-badge,
              .pill,
              .field-hint {
                font-family: var(--font-mono);
              }

              .secondary {
                color: var(--text-secondary);
              }

              .muted {
                color: var(--text-muted);
              }

              .nav-link,
              .icon-button,
              .action-button,
              .secondary-button,
              .danger-button {
                border-radius: var(--radius-sm);
                transition: var(--transition-fast);
              }

              .nav-link,
              .icon-button,
              .secondary-button,
              .danger-button {
                border: 1px solid transparent;
                background: transparent;
                color: var(--text-secondary);
                cursor: pointer;
              }

              .nav-link,
              .icon-button {
                padding: 6px 10px;
              }

              .nav-link:hover,
              .icon-button:hover,
              .secondary-button:hover,
              .danger-button:hover {
                color: var(--text-primary);
                background: var(--bg-surface-hover);
              }

              .nav-link.active {
                color: var(--text-primary);
                border-bottom: 2px solid var(--border-focus);
              }

              .action-button {
                border: none;
                padding: 10px 14px;
                background: var(--status-done);
                color: var(--text-inverse);
                font-family: var(--font-display);
                font-size: var(--text-md);
                font-weight: 700;
                letter-spacing: 0.05em;
                text-transform: uppercase;
                cursor: pointer;
              }

              .action-button:hover {
                filter: brightness(1.08);
              }

              .action-button:disabled {
                opacity: 0.3;
                cursor: not-allowed;
              }

              .secondary-button,
              .danger-button {
                padding: 8px 12px;
              }

              .secondary-button {
                border-color: var(--border-medium);
                color: var(--text-primary);
              }

              .danger-button {
                border-color: var(--status-blocked);
                color: var(--status-blocked);
              }

              .danger-button:hover {
                background: rgba(239, 68, 68, 0.14);
              }

              .pause-button {
                border-left: 3px solid var(--status-active);
              }

              .pausing-button {
                padding: 8px 12px;
                border: 1px solid var(--border-medium);
                border-left: 3px solid var(--status-active);
                border-radius: var(--radius-sm);
                background: transparent;
                color: var(--text-muted);
                cursor: not-allowed;
                pointer-events: none;
                opacity: 0.7;
                animation: pausing-pulse 1.5s ease-in-out infinite;
                font-family: var(--font-display);
                font-size: var(--text-sm);
                font-weight: 600;
                letter-spacing: 0.02em;
                text-transform: uppercase;
              }

              @keyframes pausing-pulse {
                0%, 100% { opacity: 0.5; }
                50% { opacity: 0.85; }
              }

              .resume-entrance {
                animation: resume-pop 200ms ease-out;
              }

              @keyframes resume-pop {
                from { transform: scale(0.92); opacity: 0.6; }
                to { transform: scale(1); opacity: 1; }
              }
              @keyframes spin {
                from { transform: rotate(0deg); }
                to { transform: rotate(360deg); }
              }

              .page {
                padding: var(--space-6);
                animation: fade-in-up 400ms ease forwards;
              }

              .section-card,
              .worker-card,
              .session-card,
              .setup-card,
              .history-card,
              .task-feed {
                background: var(--bg-surface);
                border: 1px solid var(--border-subtle);
                border-radius: var(--radius-lg);
                box-shadow: 0 18px 48px rgba(0, 0, 0, 0.28);
              }

              .banner {
                margin: var(--space-4);
                padding: var(--space-3) var(--space-4);
                border-radius: var(--radius-md);
                border: 1px solid var(--border-subtle);
                background: rgba(59, 130, 246, 0.12);
                color: var(--text-primary);
              }

              .banner.error {
                border-color: rgba(239, 68, 68, 0.5);
                background: rgba(239, 68, 68, 0.12);
              }

              .banner.warning {
                border-color: rgba(245, 158, 11, 0.5);
                background: rgba(245, 158, 11, 0.12);
              }

              .pipeline-strip {
                display: flex;
                align-items: center;
                gap: var(--space-2);
                padding: var(--space-3) var(--space-4);
                background: var(--bg-surface);
                border-bottom: 1px solid var(--border-subtle);
                min-height: var(--pipeline-strip-height);
                animation: fade-in-up 400ms ease forwards;
                animation-delay: 80ms;
                overflow-x: auto;
              }

              .event-feed {
                padding: var(--space-2) var(--space-4);
                background: var(--bg-surface);
                border-bottom: 1px solid var(--border-subtle);
                max-height: 220px;
                overflow-y: auto;
              }

              .event-row {
                display: flex;
                gap: var(--space-3);
                align-items: baseline;
                padding: 2px 0;
              }

              .event-row.error {
                color: var(--status-blocked);
              }

              .event-row.warning {
                color: var(--status-review);
              }

              .stage-badge,
              .status-badge,
              .pill {
                display: inline-flex;
                align-items: center;
                gap: 6px;
                padding: 2px 10px;
                border-radius: var(--radius-sm);
                font-size: var(--text-sm);
                font-weight: 500;
              }

              .stage-separator {
                color: var(--text-muted);
                font-size: var(--text-xs);
              }

              .worker-grid {
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
                gap: var(--space-4);
                margin-top: var(--space-6);
              }

              .worker-card {
                min-height: var(--worker-card-min-height);
                padding: var(--space-4);
                cursor: pointer;
                animation: fade-in-up 400ms ease forwards;
              }

              .worker-card:hover,
              .session-card:hover {
                background: var(--bg-surface-hover);
              }

              .worker-card.active {
                animation: pulse-active 3s ease-in-out infinite;
              }

              .worker-card.warning {
                border-color: rgba(245, 158, 11, 0.5);
                animation: pulse-warning 2s ease-in-out infinite;
              }

              @keyframes pulse-warning {
                0%, 100% { box-shadow: 0 0 0 0 rgba(245, 158, 11, 0); border-color: rgba(245, 158, 11, 0.5); }
                50% { box-shadow: 0 0 0 4px rgba(245, 158, 11, 0.12); border-color: rgba(245, 158, 11, 0.8); }
              }

              @keyframes pulse-idle-amber {
                0%, 100% { opacity: 0.6; }
                50% { opacity: 1.0; }
              }

              @keyframes pulse-idle-red {
                0%, 100% { opacity: 0.7; }
                50% { opacity: 1.0; text-shadow: 0 0 6px rgba(239, 68, 68, 0.5); }
              }

              .worker-card.problem {
                animation: pulse-error 1.5s ease-in-out infinite;
              }

              .worker-card.idle {
                opacity: 0.4;
                min-height: auto;
                padding: var(--space-2) var(--space-3);
                animation: breathe 4s ease-in-out infinite;
              }

              .worker-card-header {
                display: flex;
                align-items: flex-start;
                justify-content: space-between;
                gap: var(--space-3);
              }

              .worker-card-title {
                display: flex;
                flex-direction: column;
                gap: 4px;
                min-width: 0;
              }

              .worker-card-title .secondary {
                white-space: nowrap;
                overflow: hidden;
                text-overflow: ellipsis;
              }

              .detail-line {
                margin-top: var(--space-3);
                font-family: var(--font-mono);
                font-size: var(--text-sm);
                color: var(--text-secondary);
              }

              .progress-bar {
                margin-top: var(--space-3);
                display: grid;
                gap: 1px;
                height: 6px;
                border-radius: 3px;
                overflow: hidden;
                background: var(--bg-input);
              }

              .progress-bar span {
                display: block;
                background: var(--bg-input);
              }

              .progress-bar span.done {
                background: var(--status-done);
              }

              .progress-bar span.active {
                background: var(--status-active);
                animation: segment-fill 400ms ease forwards;
              }

              .progress-bar span.future {
                background: rgba(59, 130, 246, 0.08);
              }

              .log-tail,
              .log-panel,
              .intake-list,
              .preflight-panel {
                margin-top: var(--space-4);
                background: var(--bg-log);
                border-radius: var(--radius-sm);
                padding: var(--space-2) var(--space-3);
                font-size: var(--text-xs);
                line-height: 1.5;
                color: var(--text-secondary);
              }

              .log-tail {
                min-height: 104px;
                max-height: 124px;
                overflow: hidden;
              }

              .log-panel {
                margin: 0;
                border-radius: 0;
                min-height: calc(100vh - var(--topbar-height));
                padding-bottom: 96px;
                overflow: auto;
              }

              .log-line {
                animation: log-slide-in 200ms ease;
                white-space: pre-wrap;
                word-break: break-word;
              }

              .log-line.progress {
                margin: 2px 0;
                padding: 4px 8px;
                border-left: 2px solid var(--status-active);
                background: rgba(245, 158, 11, 0.1);
              }

              .log-line.error {
                color: var(--status-blocked);
              }

              .log-line.separator {
                color: var(--status-active);
                text-align: center;
                opacity: 0.7;
                padding: 8px 0;
              }

              .task-feed {
                margin-top: var(--space-6);
                overflow: hidden;
              }

              .task-row {
                display: flex;
                align-items: center;
                gap: var(--space-3);
                min-height: 36px;
                padding: 0 var(--space-4);
                border-bottom: 1px solid var(--border-subtle);
                cursor: pointer;
              }

              .task-row:last-child {
                border-bottom: none;
              }

              .task-row:hover {
                background: var(--bg-surface-hover);
              }

              .task-row.blocked {
                background: rgba(239, 68, 68, 0.08);
                border-left: 3px solid var(--status-blocked);
              }

              .task-row.active {
                border-left: 3px solid var(--status-active);
              }

              .task-row .task-actions {
                display: none;
                gap: 4px;
                margin-left: auto;
              }
              .task-row:hover .task-actions {
                display: flex;
              }

              .task-title {
                flex: 1;
                min-width: 0;
                white-space: nowrap;
                overflow: hidden;
                text-overflow: ellipsis;
              }

              .setup-shell {
                min-height: calc(100vh - var(--topbar-height));
                display: flex;
                align-items: center;
                justify-content: center;
                padding: var(--space-6);
              }

              .setup-card {
                width: min(760px, 100%);
                padding: var(--space-8);
                border-radius: var(--radius-xl);
              }

              .view-title {
                margin: 0 0 var(--space-6);
                font-family: var(--font-display);
                font-size: var(--text-2xl);
              }

              .form-grid,
              .settings-grid {
                display: grid;
                gap: var(--space-4);
              }

              .field-label {
                display: block;
                margin-bottom: var(--space-1);
                font-size: var(--text-xs);
                color: var(--text-muted);
                text-transform: uppercase;
                letter-spacing: 0.05em;
              }

              .field-hint {
                margin-top: 6px;
                font-size: var(--text-xs);
                color: var(--text-muted);
              }

              .text-input,
              .select-input,
              .search-input {
                width: 100%;
                padding: var(--space-2) var(--space-3);
                border: 1px solid var(--border-subtle);
                border-radius: var(--radius-md);
                background: var(--bg-input);
                color: var(--text-primary);
                font-family: var(--font-mono);
                font-size: var(--text-base);
              }

              .text-input:focus,
              .select-input:focus,
              .search-input:focus {
                outline: none;
                border-color: var(--border-focus);
              }

              .split-view {
                display: grid;
                grid-template-columns: 40% 60%;
                min-height: calc(100vh - var(--topbar-height));
              }

              .detail-panel {
                padding: var(--space-6);
                overflow: auto;
              }

              .metadata-grid {
                display: grid;
                gap: var(--space-4);
                margin-top: var(--space-6);
              }

              .metadata-value {
                color: var(--text-primary);
                word-break: break-word;
              }

              .constraint-list,
              .preflight-list,
              .history-list {
                display: grid;
                gap: var(--space-3);
              }

              .preflight-row,
              .intake-row {
                display: flex;
                align-items: center;
                justify-content: space-between;
                gap: var(--space-3);
                padding: 8px 0;
                border-bottom: 1px solid rgba(255, 255, 255, 0.04);
              }

              .preflight-row:last-child,
              .intake-row:last-child {
                border-bottom: none;
              }

              .preflight-output {
                margin: 0 0 var(--space-2) 22px;
                padding: var(--space-2) var(--space-3);
                background: rgba(255, 60, 60, 0.08);
                border-left: 3px solid var(--status-blocked);
                border-radius: var(--radius-sm);
                font-family: var(--font-mono);
                font-size: var(--text-xs);
                color: var(--text-secondary);
                white-space: pre-wrap;
                word-break: break-word;
                max-height: 200px;
                overflow-y: auto;
              }

              .status-dot {
                width: 10px;
                height: 10px;
                border-radius: 999px;
                flex: 0 0 auto;
              }

              .advanced-panel {
                margin-top: var(--space-3);
                padding-top: var(--space-3);
                border-top: 1px solid var(--border-subtle);
              }

              .dag-shell {
                min-height: calc(100vh - var(--topbar-height));
                background-image:
                  linear-gradient(rgba(255,255,255,0.02) 1px, transparent 1px),
                  linear-gradient(90deg, rgba(255,255,255,0.02) 1px, transparent 1px);
                background-size: 40px 40px;
              }
              .dag-canvas-root { position: relative; width: 100%; height: 100%; overflow: hidden; touch-action: none; }
              .dag-viewport { position: absolute; inset: 0; transform-origin: 0 0; }
              .dag-edges { position: absolute; overflow: visible; pointer-events: none; }
              .dag-edge.animated { stroke-dasharray: 5; animation: dag-edge-flow .5s linear infinite; }
              .dag-edges g[data-selected="true"] .dag-edge { stroke: #555; }
              @keyframes dag-edge-flow { to { stroke-dashoffset: -10; } }
              .dag-node { position: absolute; box-sizing: border-box; padding: 10px; text-align: center; cursor: grab; font-size: 12px; user-select: none; }
              .dag-node.selected { box-shadow: 0 0 0 1px var(--text-primary); }
              .dag-handle { position: absolute; left: 50%; width: 4px; height: 4px; border: 1px solid white; border-radius: 50%; background: #1a192b; transform: translateX(-50%); cursor: crosshair; }
              .dag-target-handle { top: -3px; }
              .dag-source-handle { bottom: -3px; }
              .dag-controls { position: absolute; left: 15px; bottom: 15px; display: flex; flex-direction: column; box-shadow: 0 0 2px #777; }
              .dag-controls button { width: 26px; height: 26px; border: 0; border-bottom: 1px solid #ddd; background: white; color: #999; cursor: pointer; }
              .dag-controls svg { width: 12px; height: 12px; fill: currentColor; }
              .dag-minimap { position: absolute; right: 15px; bottom: 15px; width: 200px; height: 150px; background: white; }

              .dag-canvas {
                height: calc(100vh - var(--topbar-height) - 88px);
              }

              .history-list {
                margin-top: var(--space-4);
              }

              .session-card {
                padding: var(--space-4);
                cursor: pointer;
              }

              .session-card-header {
                display: flex;
                align-items: flex-start;
                justify-content: space-between;
                gap: var(--space-4);
              }

              .retention-line {
                margin-top: var(--space-6);
                color: var(--text-muted);
                font-size: var(--text-sm);
              }

              .empty-state {
                padding: var(--space-8);
                text-align: center;
                color: var(--text-muted);
              }

              .stack {
                display: grid;
                gap: var(--space-3);
              }

              .hidden-mobile {
                display: inline-flex;
              }

              @media (max-width: 960px) {
                .split-view {
                  grid-template-columns: 1fr;
                }

                .topbar {
                  padding-top: var(--space-2);
                  padding-bottom: var(--space-2);
                  flex-direction: column;
                  align-items: flex-start;
                }

                .topbar-center,
                .topbar-nav,
                .action-row,
                .row {
                  flex-wrap: wrap;
                }

                .dag-canvas {
                  height: 60vh;
                }

                .hidden-mobile {
                  display: none;
                }
              }

              .completion-card-section {
                margin-top: var(--space-4);
              }

              .completion-card-section h4 {
                font-family: var(--font-mono);
                font-size: var(--text-sm);
                color: var(--text-secondary);
                margin-bottom: var(--space-2);
                text-transform: uppercase;
                letter-spacing: 0.05em;
              }

              .completion-code-block {
                background: var(--bg-log);
                border: 1px solid var(--border-subtle);
                border-radius: 6px;
                padding: var(--space-3);
                font-family: var(--font-mono);
                font-size: var(--text-xs);
                overflow-x: auto;
                white-space: pre;
                position: relative;
                color: var(--text-primary);
              }

              .completion-code-block .copy-btn {
                position: absolute;
                top: var(--space-2);
                right: var(--space-2);
                background: var(--bg-surface);
                border: 1px solid var(--border-subtle);
                border-radius: 4px;
                padding: 4px 8px;
                cursor: pointer;
                color: var(--text-secondary);
                font-size: var(--text-xs);
                font-family: var(--font-mono);
              }

              .completion-code-block .copy-btn:hover {
                background: var(--bg-surface-hover);
                color: var(--text-primary);
              }

              .commit-msg-textarea {
                width: 100%;
                min-height: 120px;
                background: var(--bg-log);
                border: 1px solid var(--border-subtle);
                border-radius: 6px;
                padding: var(--space-3);
                font-family: var(--font-mono);
                font-size: var(--text-xs);
                color: var(--text-primary);
                resize: vertical;
                box-sizing: border-box;
              }
            </style>
          </head>
          <body>
            <div id="switchyard-app"></div>
            <script id="switchyard-bootstrap" type="application/json">__BOOTSTRAP_JSON__</script>
            <script type="module">
const html = htm.bind(preact.h);
              const { Icon } = frontendKit;

              const bootstrap = JSON.parse(document.getElementById("switchyard-bootstrap").textContent);
              const {useEffect, useMemo, useRef, useState} = preactHooks;
              const OPERABLE_STATUSES = new Set(["created", "idle", "running", "paused", "planning", "resolving", "verifying", "auto_fixing"]);
              const ACTIVE_STATUSES = new Set(["running", "idle", "paused", "planning", "resolving", "verifying", "auto_fixing"]);
              const STATUS_COLORS = {
                done: "var(--status-done)",
                active: "var(--status-active)",
                ready: "var(--status-ready)",
                blocked: "var(--status-blocked)",
                staged: "var(--status-staged)",
                review: "var(--status-review)",
                idle: "var(--status-idle)",
                running: "var(--status-active)",
                idle: "var(--status-staged)",
                paused: "var(--status-review)",
                created: "var(--status-ready)",
                completed: "var(--status-done)",
                aborted: "var(--status-blocked)",
                verifying: "var(--status-active)",
                auto_fixing: "var(--status-review)",
                warning: "rgba(245, 158, 11, 0.9)"
              };
              const TASK_STATUS_ORDER = {
                blocked: 0,
                active: 1,
                ready: 2,
                review: 3,
                staged: 4,
                done: 5
              };

              function statusBadgeStyle(status) {
                const color = STATUS_COLORS[status] || "var(--text-secondary)";
                return {
                  color,
                  background: `${color}22`,
                  border: `1px solid ${color}55`
                };
              }

              function formatElapsed(seconds) {
                if (!seconds) {
                  return "0s";
                }
                const totalSeconds = Math.max(0, Number(seconds) || 0);
                const hours = Math.floor(totalSeconds / 3600);
                const minutes = Math.floor((totalSeconds % 3600) / 60);
                const secs = Math.floor(totalSeconds % 60);
                if (hours > 0) {
                  return `${hours}h ${minutes}m`;
                }
                if (minutes > 0) {
                  return `${minutes}m ${secs}s`;
                }
                return `${secs}s`;
              }

              function isProblemLine(line) {
                return /ERROR|FAIL|Traceback|Exception/i.test(line);
              }

              function isProgressLine(line) {
                return line.includes("##PROGRESS##");
              }

              function splitLogContent(content) {
                if (!content) {
                  return [];
                }
                return content.replace(/\\n$/, "").split("\\n").filter((line) => line.length > 0);
              }

              function dedupeSessionList(sessions, session) {
                const others = (sessions || []).filter((item) => item.id !== session.id);
                return [session, ...others];
              }

              function buildInitialSetupDraft(currentSession, settings, packs) {
                const today = new Date().toISOString().slice(0, 10);
                const config = currentSession?.config || {};
                const env = config.environment || {};
                const packName = currentSession?.pack || settings?.default_pack || packs?.[0]?.name || "";
                const selectedPackDraft = packs?.find(p => p.name === packName);
                return {
                  id: currentSession?.id || `session-${today}`,
                  name: currentSession?.name || `coding-run-${today}`,
                  pack: packName,
                  repo_root: env.COGNITIVE_SWITCHYARD_REPO_ROOT || "",
                  project_dir: env.COGNITIVE_SWITCHYARD_PROJECT_DIR || "",
                  branch: env.COGNITIVE_SWITCHYARD_BRANCH || "",
                  planner_count: config.planner_count ?? settings?.default_planners ?? 1,
                  worker_count: config.worker_count ?? selectedPackDraft?.max_workers ?? settings?.default_workers ?? 1,
                  // Blank keeps the selected pack's value; the inputs show it as a placeholder.
                  verification_interval: config.verification_interval ?? "",
                  auto_fix_enabled: config.auto_fix_enabled === true ? "enabled" : config.auto_fix_enabled === false ? "disabled" : "",
                  auto_fix_max_attempts: config.auto_fix_max_attempts ?? "",
                  poll_interval: config.poll_interval ?? 0.05,
                  task_idle_timeout: config.task_idle ?? "",
                  task_max_timeout: config.task_max ?? "",
                  session_max_timeout: config.session_max ?? ""
                };
              }

              function buildSessionRuntimeDraft(currentSession, settings, packs) {
                return buildInitialSetupDraft(currentSession, settings, packs);
              }

              function sortTasks(tasks) {
                return [...(tasks || [])].sort((left, right) => {
                  const leftRank = TASK_STATUS_ORDER[left.status] ?? 99;
                  const rightRank = TASK_STATUS_ORDER[right.status] ?? 99;
                  if (leftRank !== rightRank) {
                    return leftRank - rightRank;
                  }
                  const leftOrder = left.exec_order ?? 0;
                  const rightOrder = right.exec_order ?? 0;
                  if (leftOrder !== rightOrder) {
                    return leftOrder - rightOrder;
                  }
                  return String(left.task_id).localeCompare(String(right.task_id));
                });
              }

              function requestJson(path, options = {}) {
                return fetch(path, options).then(async (response) => {
                  if (!response.ok) {
                    const text = await response.text();
                    throw new Error(text || `${response.status} ${response.statusText}`);
                  }
                  if (response.status === 204) {
                    return null;
                  }
                  return response.json();
                });
              }

              function icon(name, attrs = {}) {
                const names = {"arrow-left":"ArrowLeft", "file-text":"FileText", "folder-open":"FolderOpen", "git-branch":"GitBranch", inbox:"Inbox", link:"Link", loader:"Loader", "refresh-cw":"RefreshCw", settings:"Settings", shield:"Shield", "trash-2":"Trash2", "check-circle":"CheckCircle", edit:"Edit", eye:"Eye"};
                return html`<${Icon} name=${names[name]} ...${attrs} />`;
              }

              function verificationReasonLabel(reason, sessionStatus) {
                const isAutoFix = sessionStatus === "auto_fixing";
                if (reason === "interval") return "Periodic interval check";
                if (reason === "task_failure" || reason === "task_auto_fix") {
                  return isAutoFix ? "Auto-fixing task failure" : "Re-verifying after task fix";
                }
                if (reason === "verification_failure") {
                  return isAutoFix ? "Auto-fixing verification failures" : "Re-verifying after auto-fix";
                }
                if (reason === "recovery_replay") return "Recovery verification";
                if (reason === "full_test_after") return "Task requires full test after completion";
                if (reason === "final") return "Final verification";
                return reason || "Scheduled verification";
              }

              function App() {
                const initialCurrentSession = OPERABLE_STATUSES.has(bootstrap.current_session?.status)
                  ? bootstrap.current_session
                  : null;
                const [view, setView] = useState(
                  initialCurrentSession
                    ? (initialCurrentSession.status === "created" ? "setup" : "monitor")
                    : "setup"
                );
                const [packs, setPacks] = useState(bootstrap.packs || []);
                const [sessions, setSessions] = useState(bootstrap.sessions || []);
                const [settings, setSettings] = useState(bootstrap.settings || {});
                const [settingsDraft, setSettingsDraft] = useState(bootstrap.settings || {});
                const [currentSession, setCurrentSession] = useState(initialCurrentSession);
                const [dashboard, setDashboard] = useState(initialCurrentSession ? (bootstrap.dashboard || null) : null);
                // No client-side idle tracking — the server computes last_activity_ago
                // from the authoritative last_output_at in the worker manager.
                const [tasks, setTasks] = useState([]);
                const [historyTasks, setHistoryTasks] = useState([]);
                const [intake, setIntake] = useState(bootstrap.intake || { locked: false, files: [] });
                const [preflight, setPreflight] = useState(null);
                const [setupDraft, setSetupDraft] = useState(
                  buildInitialSetupDraft(initialCurrentSession, bootstrap.settings || {}, bootstrap.packs || [])
                );
                const [showAdvanced, setShowAdvanced] = useState(false);
                const [repoRootInfo, setRepoRootInfo] = useState(null);
                const [repoBranches, setRepoBranches] = useState([]);
                const [selectedTask, setSelectedTask] = useState(null);
                const [taskLogs, setTaskLogs] = useState({});
                const [phaseDetail, setPhaseDetail] = useState({});
                const [taskSearch, setTaskSearch] = useState("");
                const [dag, setDag] = useState(null);
                const [message, setMessage] = useState(null);
                const [isBusy, setIsBusy] = useState(false);

                // Auto-dismiss non-error banners after 8 seconds
                useEffect(() => {
                  if (!message || message.level === "error") return;
                  const timer = setTimeout(() => setMessage(null), 8000);
                  return () => clearTimeout(timer);
                }, [message]);

                // Clear banner on view navigation
                useEffect(() => { setMessage(null); }, [view]);
                const [isPausing, setIsPausing] = useState(false);
                const wsRef = useRef(null);
                const subscribedSlotsRef = useRef(new Set());

                useEffect(() => {
                  refreshPacks();
                  refreshSessions();
                }, []);

                useEffect(() => {
                  if (!currentSession || !OPERABLE_STATUSES.has(currentSession.status)) {
                    return;
                  }
                  loadSessionData(currentSession.id, { includePreflight: currentSession.status === "created" });
                }, [currentSession?.id, currentSession?.status]);

                useEffect(() => {
                  if (!currentSession || !OPERABLE_STATUSES.has(currentSession.status)) {
                    closeSocket();
                    return undefined;
                  }
                  let unmounted = false;
                  let reconnectTimer = null;
                  let reconnectDelay = 1000;
                  const MAX_RECONNECT_DELAY = 30000;

                  function connectWebSocket() {
                    if (unmounted) return;
                    const protocol = window.location.protocol === "https:" ? "wss" : "ws";
                    const socket = new WebSocket(`${protocol}://${window.location.host}/ws`);
                    socket.onopen = () => {
                      reconnectDelay = 1000;
                      setMessage(null);
                      syncLogSubscriptions(socket, dashboard, selectedTask);
                    };
                    socket.onmessage = (event) => {
                      const payload = JSON.parse(event.data);
                      handleSocketMessage(payload);
                    };
                    socket.onclose = () => {
                      if (unmounted) return;
                      setMessage({
                        level: "warning",
                        text: `Live connection lost. Reconnecting in ${Math.round(reconnectDelay / 1000)}s...`
                      });
                      wsRef.current = null;
                      subscribedSlotsRef.current = new Set();
                      reconnectTimer = setTimeout(() => {
                        reconnectDelay = Math.min(reconnectDelay * 2, MAX_RECONNECT_DELAY);
                        connectWebSocket();
                      }, reconnectDelay);
                    };
                    socket.onerror = () => {};
                    wsRef.current = socket;
                  }

                  connectWebSocket();
                  return () => {
                    unmounted = true;
                    if (reconnectTimer) clearTimeout(reconnectTimer);
                    if (wsRef.current) {
                      wsRef.current.close();
                      wsRef.current = null;
                    }
                    subscribedSlotsRef.current = new Set();
                  };
                }, [currentSession?.id]);

                useEffect(() => {
                  syncLogSubscriptions(wsRef.current, dashboard, selectedTask);
                }, [dashboard, selectedTask?.worker_slot, currentSession?.id]);

                useEffect(() => {
                  if (!currentSession) {
                    setSetupDraft(buildSessionRuntimeDraft(null, settings, packs));
                    return;
                  }
                  if (currentSession.status === "created") {
                    setSetupDraft(buildSessionRuntimeDraft(currentSession, settings, packs));
                  }
                }, [currentSession?.id, currentSession?.status]);

                // Client-side timer: increments elapsed every second for active workers, tasks, and session.
                // The server's elapsed values are authoritative; state_update resets them. This fills the gap between pushes.
                useEffect(() => {
                  const interval = setInterval(() => {
                    setDashboard((current) => {
                      if (!current) return current;
                      const sessionStatus = current.session?.status;
                      const isSessionActive = ["planning", "resolving", "running", "verifying", "auto_fixing"].includes(sessionStatus);
                      return {
                        ...current,
                        session: isSessionActive
                          ? { ...current.session, elapsed: (current.session.elapsed || 0) + 1, run_elapsed: (current.session.run_elapsed || 0) + 1 }
                          : current.session,
                        workers: (current.workers || []).map((w) =>
                          w.status === "active"
                            ? { ...w, elapsed: (w.elapsed || 0) + 1 }
                            : w
                        ),
                      };
                    });
                  }, 1000);
                  return () => clearInterval(interval);
                }, []);

                const activeWorkers = (dashboard?.workers || []).filter((worker) => worker.status === "active").length;
                const workerCount = dashboard?.session?.effective_runtime_config?.worker_count || 0;
                const selectedPack = packs.find((pack) => pack.name === setupDraft.pack) || packs[0] || null;
                const appSessionStatus = dashboard?.session?.status || currentSession?.status || "created";
                const appRuntimeState = dashboard?.runtime_state || {};
                const filteredTaskLog = useMemo(() => {
                  if (!selectedTask) {
                    return [];
                  }
                  const lines = taskLogs[selectedTask.task_id] || [];
                  if (!taskSearch.trim()) {
                    return lines;
                  }
                  return lines.filter((entry) => entry.line.toLowerCase().includes(taskSearch.toLowerCase()));
                }, [selectedTask, taskLogs, taskSearch]);

                function closeSocket() {
                  if (wsRef.current) {
                    wsRef.current.close();
                    wsRef.current = null;
                  }
                  subscribedSlotsRef.current = new Set();
                }

                function syncLogSubscriptions(socket, nextDashboard, nextSelectedTask) {
                  if (!socket || socket.readyState !== WebSocket.OPEN) {
                    return;
                  }
                  const desired = new Set(
                    (nextDashboard?.workers || [])
                      .filter((worker) => worker.task_id && typeof worker.slot === "number")
                      .map((worker) => worker.slot)
                  );
                  if (nextSelectedTask && typeof nextSelectedTask.worker_slot === "number") {
                    desired.add(nextSelectedTask.worker_slot);
                  }
                  subscribedSlotsRef.current.forEach((slot) => {
                    if (!desired.has(slot)) {
                      socket.send(JSON.stringify({ type: "unsubscribe_logs", worker_slot: slot }));
                    }
                  });
                  desired.forEach((slot) => {
                    if (!subscribedSlotsRef.current.has(slot)) {
                      socket.send(JSON.stringify({ type: "subscribe_logs", worker_slot: slot }));
                    }
                  });
                  subscribedSlotsRef.current = desired;
                }

                async function refreshPacks() {
                  const payload = await requestJson("/api/packs");
                  setPacks(payload.packs);
                  return payload.packs;
                }

                async function refreshSessions() {
                  const payload = await requestJson("/api/sessions");
                  setSessions(payload.sessions);
                  return payload.sessions;
                }

                async function loadSessionData(sessionId, options = {}) {
                  const includePreflight = options.includePreflight ?? false;
                  try {
                    const [sessionPayload, dashboardPayload, tasksPayload, intakePayload] = await Promise.all([
                      requestJson(`/api/sessions/${sessionId}`),
                      requestJson(`/api/sessions/${sessionId}/dashboard`),
                      requestJson(`/api/sessions/${sessionId}/tasks`),
                      requestJson(`/api/sessions/${sessionId}/intake`)
                    ]);
                    setMessage(null);
                    setCurrentSession(sessionPayload.session);
                    setSessions((current) => dedupeSessionList(current, sessionPayload.session));
                    setDashboard(dashboardPayload);
                    setTasks(sortTasks(tasksPayload.tasks));
                    setHistoryTasks([]);
                    setIntake(intakePayload);
                    if (includePreflight && sessionPayload.session.status === "created") {
                      await refreshPreflight(sessionId);
                    } else if (sessionPayload.session.status !== "created") {
                      setPreflight(null);
                    }
                  } catch (error) {
                    setMessage({ level: "error", text: `Failed to load session data: ${error.message}` });
                  }
                }

                async function loadHistorySession(sessionId) {
                  try {
                    const [sessionPayload, tasksPayload] = await Promise.all([
                      requestJson(`/api/sessions/${sessionId}`),
                      requestJson(`/api/sessions/${sessionId}/tasks`)
                    ]);
                    setMessage(null);
                    setCurrentSession(sessionPayload.session);
                    setSessions((current) => dedupeSessionList(current, sessionPayload.session));
                    setDashboard(null);
                    setTasks([]);
                    setHistoryTasks(sortTasks(tasksPayload.tasks));
                    setIntake({ locked: false, files: [] });
                    setPreflight(null);
                  } catch (error) {
                    setMessage({ level: "error", text: `Failed to load history session: ${error.message}` });
                  }
                }

                async function refreshPreflight(sessionId = currentSession?.id) {
                  if (!sessionId) {
                    return null;
                  }
                  try {
                    const payload = await requestJson(`/api/sessions/${sessionId}/preflight`, { method: "POST" });
                    setMessage(null);
                    setPreflight(payload);
                    return payload;
                  } catch (error) {
                    setMessage({ level: "error", text: `Preflight failed: ${error.message}` });
                    return null;
                  }
                }

                async function openTaskDetail(taskId) {
                  if (!currentSession) {
                    return;
                  }
                  try {
                    const [taskPayload, logPayload] = await Promise.all([
                      requestJson(`/api/sessions/${currentSession.id}/tasks/${taskId}`),
                      requestJson(`/api/sessions/${currentSession.id}/tasks/${taskId}/log?offset=0&limit=400`)
                    ]);
                    setMessage(null);
                    setSelectedTask(taskPayload.task);
                    setTaskLogs((current) => ({
                      ...current,
                      [taskId]: splitLogContent(logPayload.content).map((line) => ({ line, ts: logPayload.mtime_iso || null }))
                    }));
                    setTaskSearch("");
                    setView("task-detail");
                  } catch (error) {
                    setMessage({ level: "error", text: `Unable to open task detail: ${error.message}` });
                  }
                }

                async function openDag() {
                  if (!currentSession) {
                    return;
                  }
                  try {
                    const payload = await requestJson(`/api/sessions/${currentSession.id}/dag`);
                    setMessage(null);
                    setDag(payload);
                    setView("dag");
                  } catch (error) {
                    setMessage({ level: "error", text: `Unable to load DAG: ${error.message}` });
                  }
                }

                async function fetchBranches(repoPath) {
                  try {
                    const data = await requestJson("/api/repo-branches", {
                      method: "POST",
                      headers: { "Content-Type": "application/json" },
                      body: JSON.stringify({ path: repoPath })
                    });
                    setRepoBranches(data.branches || []);
                    if (data.current) {
                      setSetupDraft((draft) => ({ ...draft, branch: draft.branch || data.current }));
                    }
                  } catch {
                    setRepoBranches([]);
                  }
                }

                async function resolveRepoRoot(rawPath) {
                  if (!rawPath || !rawPath.trim()) {
                    setRepoRootInfo(null);
                    setRepoBranches([]);
                    return;
                  }
                  try {
                    const info = await requestJson("/api/resolve-path", {
                      method: "POST",
                      headers: { "Content-Type": "application/json" },
                      body: JSON.stringify({ path: rawPath })
                    });
                    setRepoRootInfo(info);
                    const resolvedPath = info.resolved || rawPath;
                    if (info.resolved && info.resolved !== rawPath) {
                      setSetupDraft((draft) => ({ ...draft, repo_root: info.resolved }));
                    }
                    if (info.is_git) {
                      fetchBranches(resolvedPath);
                    } else {
                      setRepoBranches([]);
                    }
                  } catch {
                    setRepoRootInfo(null);
                    setRepoBranches([]);
                  }
                }

                async function handleBrowseRepoRoot() {
                  try {
                    const result = await requestJson("/api/browse-directory", { method: "POST" });
                    if (result.path) {
                      setMessage(null);
                      setSetupDraft((draft) => ({ ...draft, repo_root: result.path }));
                      resolveRepoRoot(result.path);
                    }
                  } catch (error) {
                    setMessage({ level: "error", text: `Browse failed: ${error.message}` });
                  }
                }

                async function handleBrowseProjectDir() {
                  try {
                    const result = await requestJson("/api/browse-directory", { method: "POST" });
                    if (result.path) {
                      const repoRoot = setupDraft.repo_root;
                      if (repoRoot && result.path.startsWith(repoRoot + "/")) {
                        setMessage(null);
                        setSetupDraft((draft) => ({ ...draft, project_dir: result.path.slice(repoRoot.length + 1) }));
                      } else if (repoRoot && result.path === repoRoot) {
                        setMessage({ level: "warning", text: "Selected directory is the repo root itself — leave Project Directory blank for single-project repos." });
                      } else {
                        setMessage({ level: "error", text: "Selected directory is not inside the Repository Root." });
                      }
                    }
                  } catch (error) {
                    setMessage({ level: "error", text: `Browse failed: ${error.message}` });
                  }
                }

                async function handleCreateBranch(repoPath, branchName, fromBranch) {
                  await requestJson("/api/repo-create-branch", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ repo_path: repoPath, branch_name: branchName, from_branch: fromBranch })
                  });
                  await fetchBranches(repoPath);
                  setSetupDraft((draft) => ({ ...draft, branch: branchName }));
                }

                async function handleDiscardDraft() {
                  if (!currentSession) return;
                  setIsBusy(true);
                  try {
                    await requestJson(`/api/sessions/${currentSession.id}`, { method: "DELETE" });
                    setCurrentSession(null);
                    setSessions((current) => current.filter((s) => s.id !== currentSession.id));
                    setSetupDraft(buildInitialSetupDraft(null, settings, packs));
                    setIntake({ locked: false, files: [] });
                    setPreflight(null);
                    setRepoRootInfo(null);
                    setMessage({ level: "info", text: "Session reset." });
                  } catch (error) {
                    setMessage({ level: "error", text: `Unable to discard draft: ${error.message}` });
                  } finally {
                    setIsBusy(false);
                  }
                }

                async function handleCreateDraftSession() {
                  setIsBusy(true);
                  try {
                    // Build config with only valid overrides — omit NaN/0/null so
                    // the backend uses pack defaults for unset fields.
                    const config = {};
                    const env = {};
                    if (setupDraft.repo_root) env.COGNITIVE_SWITCHYARD_REPO_ROOT = setupDraft.repo_root;
                    if (setupDraft.project_dir) env.COGNITIVE_SWITCHYARD_PROJECT_DIR = setupDraft.project_dir;
                    if (setupDraft.branch && setupDraft.branch !== "__new__") env.COGNITIVE_SWITCHYARD_BRANCH = setupDraft.branch;
                    if (Object.keys(env).length > 0) config.environment = env;
                    const intField = (key, val) => { const n = parseInt(val, 10); if (n > 0) config[key] = n; };
                    const floatField = (key, val) => { const n = parseFloat(val); if (n > 0) config[key] = n; };
                    intField("planner_count", setupDraft.planner_count);
                    intField("worker_count", setupDraft.worker_count);
                    intField("verification_interval", setupDraft.verification_interval);
                    intField("auto_fix_max_attempts", setupDraft.auto_fix_max_attempts);
                    floatField("poll_interval", setupDraft.poll_interval);
                    // Timeouts accept 0 ("no limit"); a blank field keeps the pack default.
                    const timeoutField = (key, val) => {
                      if (val === "" || val === null || val === undefined) return;
                      const n = parseInt(val, 10);
                      if (n >= 0) config[key] = n;
                    };
                    timeoutField("task_idle", setupDraft.task_idle_timeout);
                    timeoutField("task_max", setupDraft.task_max_timeout);
                    timeoutField("session_max", setupDraft.session_max_timeout);
                    if (setupDraft.auto_fix_enabled === "enabled" || setupDraft.auto_fix_enabled === "disabled") {
                      config.auto_fix_enabled = setupDraft.auto_fix_enabled === "enabled";
                    }
                    const payload = await requestJson("/api/sessions", {
                      method: "POST",
                      headers: { "Content-Type": "application/json" },
                      body: JSON.stringify({
                        id: setupDraft.id,
                        name: setupDraft.name,
                        pack: setupDraft.pack,
                        config: Object.keys(config).length > 0 ? config : undefined
                      })
                    });
                    setCurrentSession(payload.session);
                    setSessions((current) => dedupeSessionList(current, payload.session));
                    setMessage({ level: "info", text: "Session created. Add intake files, run preflight, then start." });
                    setView("setup");
                    await loadSessionData(payload.session.id, { includePreflight: true });
                  } catch (error) {
                    setMessage({ level: "error", text: `Unable to create session: ${error.message}`, sessionId: setupDraft.id });
                  } finally {
                    setIsBusy(false);
                  }
                }

                async function handleStartSession() {
                  if (!currentSession) {
                    await handleCreateDraftSession();
                    return;
                  }
                  setIsBusy(true);
                  try {
                    await requestJson(`/api/sessions/${currentSession.id}/start`, { method: "POST" });
                    setMessage({ level: "info", text: "Session started." });
                    // Load dashboard data first so monitor has content when we switch
                    await loadSessionData(currentSession.id, { includePreflight: false });
                    setView("monitor");
                  } catch (error) {
                    setMessage({ level: "error", text: `Unable to start session: ${error.message}`, sessionId: currentSession?.id });
                  } finally {
                    setIsBusy(false);
                  }
                }

                async function handleSessionControl(action) {
                  if (!currentSession) {
                    return;
                  }
                  const needsConfirm = action === "abort" || action === "end";
                  const confirmMsg = action === "abort" ? `Abort session ${currentSession.name}?` : `End session ${currentSession.name}? This will clean up the worktree and write the summary.`;
                  const confirmed = !needsConfirm || window.confirm(confirmMsg);
                  if (!confirmed) {
                    return;
                  }
                  try {
                    await requestJson(`/api/sessions/${currentSession.id}/${action}`, { method: "POST" });
                    setMessage(null);
                    if (action === "pause") {
                      setIsPausing(true);
                    }
                    await loadSessionData(currentSession.id, { includePreflight: currentSession.status === "created" });
                    await refreshSessions();
                    // If the session is already paused/terminal after refetch, clear the transitional state
                    if (action === "pause") {
                      setCurrentSession((s) => {
                        if (s && (s.status === "paused" || s.status === "completed" || s.status === "aborted")) {
                          setIsPausing(false);
                        }
                        return s;
                      });
                    }
                  } catch (error) {
                    setIsPausing(false);
                    setMessage({ level: "error", text: `Unable to ${action} session: ${error.message}`, sessionId: currentSession?.id });
                  }
                }

                async function handleSettingsSave() {
                  try {
                    const payload = await requestJson("/api/settings", {
                      method: "PUT",
                      headers: { "Content-Type": "application/json" },
                      body: JSON.stringify(settingsDraft)
                    });
                    setSettings(payload.settings);
                    setSettingsDraft(payload.settings);
                    setMessage({ level: "info", text: "Settings saved." });
                  } catch (error) {
                    setMessage({ level: "error", text: `Unable to save settings: ${error.message}` });
                  }
                }

                async function handleOpenIntake() {
                  if (!currentSession) {
                    return;
                  }
                  try {
                    await requestJson(`/api/sessions/${currentSession.id}/open-intake`, { method: 'POST' });
                    setMessage(null);
                  } catch (error) {
                    setMessage({ level: "error", text: `Unable to open intake folder: ${error.message}` });
                  }
                }

                async function handleOpenIntakeTerminal() {
                  if (!currentSession) {
                    return;
                  }
                  try {
                    await requestJson(`/api/sessions/${currentSession.id}/open-intake-terminal`, { method: 'POST' });
                    setMessage(null);
                  } catch (error) {
                    setMessage({ level: "error", text: `Unable to open intake terminal: ${error.message}` });
                  }
                }

                async function handleRevealFile(path) {
                  if (!currentSession) {
                    return;
                  }
                  try {
                    await requestJson(
                      `/api/sessions/${currentSession.id}/reveal-file?path=${encodeURIComponent(path)}`,
                      { method: 'POST' }
                    );
                    setMessage(null);
                  } catch (error) {
                    setMessage({ level: "error", text: `Unable to reveal file: ${error.message}` });
                  }
                }

                async function handleMoveTask(taskId, targetStatus) {
                  if (!currentSession) return;
                  try {
                    await requestJson(
                      `/api/sessions/${currentSession.id}/tasks/${taskId}/move`,
                      { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ target_status: targetStatus }) }
                    );
                    setMessage({ level: "info", text: `Task ${taskId} moved to ${targetStatus}` });
                  } catch (err) {
                    setMessage({ level: "error", text: `Move failed: ${err.message}` });
                  }
                }

                const [isRescanning, setIsRescanning] = useState(false);

                async function handleRescan() {
                  if (!currentSession) return;
                  setIsRescanning(true);
                  try {
                    const res = await fetch(`/api/sessions/${currentSession.id}/rescan`, { method: "POST" });
                    if (!res.ok) throw new Error(await res.text());
                    const data = await res.json();
                    const count = data.reconciled.length;
                    const orphaned = data.orphaned.length;
                    let text = "Rescan: no changes";
                    if (count > 0 || orphaned > 0) {
                      const parts = [];
                      if (count > 0) parts.push(`${count} task${count !== 1 ? "s" : ""} reconciled`);
                      if (orphaned > 0) parts.push(`${orphaned} orphaned`);
                      text = "Rescan: " + parts.join(", ");
                    }
                    setMessage({ level: "info", text });
                  } catch (error) {
                    setMessage({ level: "error", text: `Rescan failed: ${error.message}` });
                  } finally {
                    setIsRescanning(false);
                  }
                }

                const [isReprocessing, setIsReprocessing] = useState(false);

                async function handleReprocess() {
                  if (!currentSession) return;
                  setIsReprocessing(true);
                  try {
                    await fetch(`/api/sessions/${currentSession.id}/rescan`, { method: "POST" });
                    const res = await fetch(`/api/sessions/${currentSession.id}/reprocess`, { method: "POST" });
                    if (!res.ok) {
                      const body = await res.json().catch(() => ({ detail: res.statusText }));
                      throw new Error(body.detail || res.statusText);
                    }
                    setMessage({ level: "info", text: "Reprocessing started — pipeline will re-run from current state." });
                  } catch (error) {
                    setMessage({ level: "error", text: `Reprocess failed: ${error.message}` });
                  } finally {
                    setIsReprocessing(false);
                  }
                }

                async function handleOpenHistorySession(session) {
                  setSelectedTask(null);
                  setDag(null);
                  setView("history");
                  await loadHistorySession(session.id);
                }

                async function handlePurgeSession(sessionId) {
                  const target = sessions.find((session) => session.id === sessionId);
                  if (!target) {
                    return;
                  }
                  const confirmed = window.confirm(`Delete session ${target.name} and all its artifacts?`);
                  if (!confirmed) {
                    return;
                  }
                  try {
                    await requestJson(`/api/sessions/${sessionId}`, { method: "DELETE" });
                    setMessage(null);
                    const nextSessions = (await refreshSessions()).filter((session) => session.id !== sessionId);
                    if (currentSession?.id === sessionId) {
                      setCurrentSession(null);
                      setDashboard(null);
                      setTasks([]);
                      setHistoryTasks([]);
                      setIntake({ locked: false, files: [] });
                      setPreflight(null);
                      setView("setup");
                    }
                    setSessions(nextSessions);
                  } catch (error) {
                    setMessage({ level: "error", text: `Unable to purge session: ${error.message}` });
                  }
                }

                async function handlePurgeAll() {
                  const completedCount = sessions.filter((session) =>
                    session.status === "completed" || session.status === "aborted"
                  ).length;
                  if (completedCount === 0) {
                    return;
                  }
                  const confirmed = window.confirm(`Delete ${completedCount} completed sessions?`);
                  if (!confirmed) {
                    return;
                  }
                  try {
                    await requestJson("/api/sessions", { method: "DELETE" });
                    setMessage(null);
                    await refreshSessions();
                  } catch (error) {
                    setMessage({ level: "error", text: `Unable to purge sessions: ${error.message}` });
                  }
                }

                async function handleForceReset(sessionId) {
                  const confirmed = window.confirm(
                    "Force reset will abort the session (if running), tear down its worktree, " +
                    "and delete all data. This cannot be undone. Continue?"
                  );
                  if (!confirmed) return;
                  setIsBusy(true);
                  try {
                    await requestJson(`/api/sessions/${sessionId}/force-reset`, { method: "POST" });
                    setCurrentSession(null);
                    setDashboard(null);
                    setTasks([]);
                    setHistoryTasks([]);
                    setIntake({ locked: false, files: [] });
                    setPreflight(null);
                    setRepoRootInfo(null);
                    setSessions((current) => current.filter((s) => s.id !== sessionId));
                    setSetupDraft(buildInitialSetupDraft(null, settings, packs));
                    setView("setup");
                    setMessage({ level: "info", text: "Session force-reset complete." });
                  } catch (error) {
                    setMessage({ level: "error", text: `Force reset failed: ${error.message}` });
                  } finally {
                    setIsBusy(false);
                  }
                }

                function handleSocketMessage(messagePayload) {
                  if (messagePayload.type === "state_update") {
                    const incomingStatus = messagePayload.data?.session?.status;
                    if (incomingStatus === "paused" || incomingStatus === "completed" || incomingStatus === "aborted") {
                      setIsPausing(false);
                    }
                    setDashboard(messagePayload.data);
                    setCurrentSession((current) => {
                      if (!current) {
                        return current;
                      }
                      const nextSession = {
                        ...current,
                        status: incomingStatus,
                        effective_runtime_config: messagePayload.data.session.effective_runtime_config,
                        config: messagePayload.data.session.config
                      };
                      setSessions((sessionsState) => dedupeSessionList(sessionsState, nextSession));
                      return nextSession;
                    });
                    // Auto-navigate to monitor when session transitions to active state
                    if (ACTIVE_STATUSES.has(incomingStatus)) {
                      setView((currentView) => currentView === "setup" ? "monitor" : currentView);
                    }
                    // Clear stale streaming logs when verification/auto-fix phases start fresh
                    if (incomingStatus === "verifying") {
                      setTaskLogs(current => {
                        const next = { ...current };
                        delete next["__phase_verification__"];
                        delete next["__phase_auto_fix__"];
                        return next;
                      });
                    }
                    if (incomingStatus === "auto_fixing") {
                      setTaskLogs(current => {
                        const next = { ...current };
                        delete next["__phase_auto_fix__"];
                        delete next["__phase_verification__"];
                        return next;
                      });
                    }
                    return;
                  }
                  if (messagePayload.type === "log_line") {
                    const workerSlot = messagePayload.data.worker_slot;
                    const taskId = messagePayload.data.task_id;
                    // Auto-clear idle warning if this worker resumed output
                    setMessage((current) => {
                      if (current && current.level === "warning" && current.workerSlot === workerSlot) {
                        return null;
                      }
                      return current;
                    });
                    setDashboard((current) => {
                      if (!current) {
                        return current;
                      }
                      const workers = (current.workers || []).map((worker) => (
                        worker.slot === workerSlot
                          ? { ...worker, last_log_line: messagePayload.data.line }
                          : worker
                      ));
                      return { ...current, workers };
                    });
                    setTaskLogs((current) => ({
                      ...current,
                      [taskId]: [...(current[taskId] || []), { line: messagePayload.data.line, ts: messagePayload.data.timestamp || null }].slice(-400)
                    }));
                    return;
                  }
                  if (messagePayload.type === "progress_detail") {
                    if (messagePayload.data.worker_slot === -1) {
                      setPhaseDetail((current) => ({
                        ...current,
                        [messagePayload.data.task_id]: messagePayload.data.detail,
                      }));
                    } else {
                      const detailSlot = messagePayload.data.worker_slot;
                      const detailContent = messagePayload.data.detail || "";
                      setDashboard((current) => {
                        if (!current) {
                          return current;
                        }
                        const workers = (current.workers || []).map((worker) => (
                          worker.slot === detailSlot
                            ? { ...worker, detail: detailContent }
                            : worker
                        ));
                        return { ...current, workers };
                      });
                    }
                    return;
                  }
                  if (messagePayload.type === "task_status_change") {
                    setTasks((current) => sortTasks(
                      current.map((task) => (
                        task.task_id === messagePayload.data.task_id
                          ? {
                              ...task,
                              status: messagePayload.data.new_status,
                              worker_slot: messagePayload.data.worker_slot ?? task.worker_slot,
                              elapsed: messagePayload.data.elapsed ?? task.elapsed,
                              started_at: messagePayload.data.started_at ?? task.started_at,
                              completed_at: messagePayload.data.completed_at ?? task.completed_at,
                            }
                          : task
                      ))
                    ));
                    return;
                  }
                  if (messagePayload.type === "alert") {
                    setMessage({
                      level: messagePayload.data.severity === "error" ? "error" : "warning",
                      text: messagePayload.data.message,
                      workerSlot: messagePayload.data.worker_slot ?? null
                    });
                  }
                }

                return (
                  html`<div class=${"app-shell"}> <${TopBar} currentSession=${currentSession} currentView=${view} workerCount=${workerCount} activeWorkers=${activeWorkers} elapsed=${dashboard?.session?.elapsed || 0} runElapsed=${dashboard?.session?.run_elapsed || 0} runNumber=${dashboard?.session?.run_number || 0} onNavigate=${setView} isPausing=${isPausing} onPause=${() => handleSessionControl("pause")} onResume=${() => handleSessionControl("resume")} onAbort=${() => handleSessionControl("abort")} onEnd=${() => handleSessionControl("end")} onNewRun=${() => handleSessionControl("resume")} /> ${message ? (
                      html`<div class=${`banner ${message.level === "error" ? "error" : message.level === "warning" ? "warning" : ""}`} style=${{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}> <div style=${{ flex: 1 }}> <span>${message.text}</span> ${message.level === "error" && message.sessionId ? (
                            html`<button type=${"button"} class=${"secondary-button"} style=${{ marginLeft: '12px', fontSize: 'var(--text-xs)', padding: '2px 8px' }} onClick=${() => handleForceReset(message.sessionId)}> Force Reset </button>`
                          ) : null} </div> <button type=${"button"} onClick=${() => setMessage(null)} style=${{ background: 'none', border: 'none', color: 'inherit', cursor: 'pointer',
                                   fontSize: '18px', padding: '0 0 0 12px', lineHeight: 1, opacity: 0.7 }} title=${"Dismiss"} onMouseOver=${(e) => e.currentTarget.style.opacity = '1'} onMouseOut=${(e) => e.currentTarget.style.opacity = '0.7'}> × </button> </div>`
                    ) : null} ${view === "monitor" ? (
                      html`<${MonitorView} dashboard=${dashboard} currentSession=${currentSession} tasks=${tasks} taskLogs=${taskLogs} phaseDetail=${phaseDetail} onOpenTask=${openTaskDetail} onOpenDag=${openDag} onRevealFile=${handleRevealFile} onMoveTask=${handleMoveTask} onRescan=${handleRescan} isRescanning=${isRescanning} onReprocess=${handleReprocess} isReprocessing=${isReprocessing} />`
                    ) : null} ${view === "setup" ? (
                      html`<${SetupView} currentSession=${currentSession} setupDraft=${setupDraft} setSetupDraft=${setSetupDraft} selectedPack=${selectedPack} packs=${packs} intake=${intake} preflight=${preflight} settings=${settings} showAdvanced=${showAdvanced} setShowAdvanced=${setShowAdvanced} isBusy=${isBusy} repoRootInfo=${repoRootInfo} repoBranches=${repoBranches} onCreateDraft=${handleCreateDraftSession} onStartSession=${handleStartSession} onRefreshIntake=${() => currentSession && loadSessionData(currentSession.id, { includePreflight: true })} onRunPreflight=${async () => {
                  setIsBusy(true);
                  try { await refreshPreflight(); } finally { setIsBusy(false); }
                }} onOpenIntake=${handleOpenIntake} onOpenIntakeTerminal=${handleOpenIntakeTerminal} onRevealFile=${handleRevealFile} onBrowseRepoRoot=${handleBrowseRepoRoot} onBrowseProjectDir=${handleBrowseProjectDir} onResolveRepoRoot=${resolveRepoRoot} onCreateBranch=${handleCreateBranch} onDiscardDraft=${handleDiscardDraft} onNewRun=${() => handleSessionControl("resume")} onNavigate=${setView} />`
                    ) : null} ${view === "history" ? (
                      html`<${HistoryView} sessions=${sessions} settings=${settings} selectedSession=${currentSession && !OPERABLE_STATUSES.has(currentSession.status) ? currentSession : null} selectedTasks=${historyTasks} onOpenSession=${handleOpenHistorySession} onOpenSettings=${() => setView("settings")} onPurgeSession=${handlePurgeSession} onPurgeAll=${handlePurgeAll} />`
                    ) : null} ${view === "settings" ? (
                      html`<${SettingsView} settingsDraft=${settingsDraft} setSettingsDraft=${setSettingsDraft} packs=${packs} onSave=${handleSettingsSave} />`
                    ) : null} ${view === "task-detail" ? (
                      html`<${TaskDetailView} task=${selectedTask} currentSession=${currentSession} logLines=${filteredTaskLog} taskLogs=${taskLogs} sessionStatus=${appSessionStatus} runtimeState=${appRuntimeState} searchValue=${taskSearch} onSearchChange=${setTaskSearch} onBack=${() => setView("monitor")} onMoveTask=${handleMoveTask} onRevealFile=${handleRevealFile} />`
                    ) : null} ${view === "dag" ? (
                      html`<${DagView} dag=${dag} liveTasks=${tasks} onBack=${() => setView("monitor")} onOpenTask=${openTaskDetail} />`
                    ) : null} </div>`
                );
              }

              function TopBar({
                currentSession,
                currentView,
                workerCount,
                activeWorkers,
                elapsed,
                runElapsed,
                runNumber,
                onNavigate,
                isPausing,
                onPause,
                onResume,
                onAbort,
                onEnd,
                onNewRun
              }) {
                const sessionStatus = currentSession?.status || "none";
                const isActive = ["planning", "resolving", "running", "verifying", "auto_fixing"].includes(sessionStatus);
                // Client-side auto-increment timers
                const [sessionTick, setSessionTick] = useState(elapsed);
                const [runTick, setRunTick] = useState(runElapsed);
                useEffect(() => { setSessionTick(elapsed); }, [elapsed]);
                useEffect(() => { setRunTick(runElapsed); }, [runElapsed]);
                useEffect(() => {
                  if (!isActive) return;
                  const timer = setInterval(() => {
                    setSessionTick(prev => prev + 1);
                    setRunTick(prev => prev + 1);
                  }, 1000);
                  return () => clearInterval(timer);
                }, [isActive]);
                const displayedRunTime = isActive ? runTick : runElapsed;
                return (
                  html`<header class=${"topbar"}> <div class=${"brand"}>Cognitive Switchyard</div> <div class=${"topbar-center"}> <span class=${"session-text secondary"}> ${currentSession ? (
                          html`<${preact.Fragment}> ${currentSession.name} ${" | "} <span class=${"status-badge"} style=${statusBadgeStyle(sessionStatus)}>${sessionStatus}</span> ${" | "} ${runNumber > 0 ? (
                              html`<span title=${"Current run time"}> ${"Run #"}${runNumber}${": "}${formatElapsed(displayedRunTime)} </span>`
                            ) : null} ${runNumber > 0 ? (
                              html`<span style=${{ marginLeft: '0.75em', color: 'var(--text-primary)' }} title=${"Total active time across all runs"}> ${"("}${formatElapsed(sessionTick)}${" cumulative)"} </span>`
                            ) : null} <//>`
                        ) : "No active session"} </span> ${currentSession ? (
                        html`<span class=${"session-text muted hidden-mobile"}>${`${activeWorkers}/${workerCount} active`}</span>`
                      ) : null} </div> <nav class=${"topbar-nav"}> <button type=${"button"} class=${`nav-link${currentView === "setup" ? " active" : ""}`} onClick=${() => onNavigate("setup")}>Setup</button> <button type=${"button"} class=${`nav-link${currentView === "monitor" ? " active" : ""}`} onClick=${() => onNavigate("monitor")}>Monitor</button> <button type=${"button"} class=${`nav-link${currentView === "history" ? " active" : ""}`} onClick=${() => onNavigate("history")}>History</button> ${isPausing ? (
                        html`<button type=${"button"} class=${"pausing-button"} disabled>⏸ Pausing…</button>`
                      ) : ["planning", "resolving", "running", "verifying", "auto_fixing"].includes(currentSession?.status) ? (
                        html`<button type=${"button"} class=${"secondary-button pause-button"} onClick=${onPause}>❚❚ Pause</button>`
                      ) : currentSession?.status === "paused" ? (
                        html`<button type=${"button"} class=${"action-button resume-entrance"} onClick=${onResume}>▶ Resume</button>`
                      ) : null} ${currentSession?.status === "idle" ? (
                        html`<${preact.Fragment}> <button type=${"button"} class=${"action-button"} onClick=${onNewRun}>New Run</button> <button type=${"button"} class=${"secondary-button"} onClick=${onEnd}>End Session</button> <//>`
                      ) : null} ${currentSession && !["completed", "aborted", "idle"].includes(currentSession.status) ? (
                        html`<button type=${"button"} class=${"danger-button"} onClick=${onAbort}>Abort</button>`
                      ) : null} <button type=${"button"} class=${"icon-button"} onClick=${() => onNavigate("settings")} aria-label=${"Settings"}> ${icon("settings", { width: 18, height: 18 })} </button> </nav> </header>`
                );
              }

              function PipelineStrip({ pipeline, pipelineDirs, sessionStatus, currentSession, onRevealFile, onOpenDag, onRescan, isRescanning, onReprocess, isReprocessing, canReprocess }) {
                const stages = [
                  ["intake", "Intake"],
                  ["planning", "Planning"],
                  ["staged", "Staged"],
                  ["review", "Review"],
                  ["ready", "Ready"],
                  ["active", "Active"],
                  ["verifying", "Verify"],
                  ["done", "Done"],
                  ["blocked", "Blocked"]
                ];
                const STAGE_ORDER = { intake: 0, planning: 1, staged: 2, review: 3, ready: 4, active: 5, verifying: 6, done: 7, blocked: 8 };
                const STATUS_TO_ACTIVE_STAGE = {
                  planning: "planning",
                  resolving: "staged",
                  running: "active",
                  verifying: "verifying",
                  auto_fixing: "verifying",
                  completed: "done",
                  aborted: "blocked"
                };
                const activeStageKey = STATUS_TO_ACTIVE_STAGE[sessionStatus] || null;
                const activeStageOrder = activeStageKey ? STAGE_ORDER[activeStageKey] : -1;

                return (
                  html`<div class=${"pipeline-strip"}> ${stages.map(([key, label], index) => {
                      const count = pipeline[key] || 0;
                      const stageOrder = STAGE_ORDER[key];
                      const isActive = key === activeStageKey;
                      const isPast = activeStageOrder > 0 && stageOrder < activeStageOrder && count === 0;
                      const hasItems = count > 0;
                      const isReviewWithItems = key === "review" && hasItems;
                      const isBlocked = key === "blocked" && hasItems;
                      let badgeColor = "var(--text-muted)";
                      let badgeBg = "transparent";
                      let badgeAnimation = "none";
                      let badgeBorder = "1px solid var(--border-subtle)";
                      let badgeOpacity = 1;
                      if (isBlocked) {
                        badgeColor = "var(--status-blocked)";
                        badgeBg = "rgba(239, 68, 68, 0.15)";
                        badgeAnimation = "pulse-error 2s ease-in-out infinite";
                        badgeBorder = "1px solid rgba(239, 68, 68, 0.4)";
                      } else if (isActive) {
                        badgeColor = "var(--status-active)";
                        badgeBg = "rgba(245, 158, 11, 0.15)";
                        badgeAnimation = "pulse-active 3s ease-in-out infinite";
                        badgeBorder = "1px solid rgba(245, 158, 11, 0.4)";
                      } else if (isReviewWithItems) {
                        badgeColor = "var(--status-review)";
                        badgeBg = "rgba(249, 115, 22, 0.15)";
                        badgeBorder = "1px solid rgba(249, 115, 22, 0.4)";
                      } else if (hasItems) {
                        badgeColor = STATUS_COLORS[key] || "var(--text-secondary)";
                        badgeBg = `${STATUS_COLORS[key] || "var(--text-secondary)"}22`;
                      } else if (isPast) {
                        badgeOpacity = 0.35;
                      }
                      return (
                        html`<${preact.Fragment} key=${key}> <button type=${"button"} class=${"stage-badge"} title=${pipelineDirs[key] ? `Open ${label} directory` : label} onClick=${() => pipelineDirs[key] && currentSession && onRevealFile(pipelineDirs[key])} style=${{
                              color: badgeColor,
                              background: badgeBg,
                              animation: badgeAnimation,
                              cursor: "pointer",
                              border: badgeBorder,
                              opacity: badgeOpacity,
                              transition: "all 300ms ease",
                            }}> ${`${label}(${count})`} </button> ${index < stages.length - 1 ? (
                            html`<span class=${"stage-separator"} style=${{ opacity: isPast ? 0.3 : 1 }}>${">"}</span>`
                          ) : null} <//>`
                      );
                    })} <button type=${"button"} class=${"icon-button"} onClick=${onOpenDag} aria-label=${"Open DAG"}> ${icon("git-branch", { width: 18, height: 18 })} </button> <button type=${"button"} class=${"icon-button"} onClick=${onRescan} disabled=${isRescanning || !currentSession} aria-label=${"Rescan filesystem"} title=${"Rescan: reconcile filesystem state into database"} style=${{ position: "relative" }}> ${isRescanning
                        ? icon("loader", { width: 18, height: 18, style: { animation: "spin 1s linear infinite" } })
                        : icon("refresh-cw", { width: 18, height: 18 })} </button> <button type=${"button"} class=${"icon-button"} onClick=${onReprocess} disabled=${!canReprocess || isReprocessing} aria-label=${"Reprocess pipeline"} title=${"Reprocess: re-run planning, resolution, and execution on current filesystem state"} style=${{ position: "relative" }}> ${isReprocessing
                        ? icon("loader", { width: 18, height: 18, style: { animation: "spin 1s linear infinite" } })
                        : html`<svg xmlns=${"http://www.w3.org/2000/svg"} width=${"18"} height=${"18"} viewBox=${"0 0 24 24"} fill=${"none"} stroke=${"currentColor"} stroke-width=${"2"} stroke-linecap=${"round"} stroke-linejoin=${"round"}><path d=${"M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"} /><path d=${"M3 3v5h5"} /></svg>`} </button> </div>`
                );
              }

              function filterLogLine(line) {
                // Returns: { show: boolean, text: string }
                // - If line is not JSON: show as-is
                // - If line is JSON with extractable human text: show the extracted text
                // - If line is JSON with no useful text: suppress
                try {
                  const parsed = JSON.parse(line);
                  // Claude CLI assistant messages: extract content[].text
                  if (parsed.type === "assistant" && Array.isArray(parsed.message?.content)) {
                    const texts = parsed.message.content
                      .filter(block => block.type === "text" && block.text)
                      .map(block => block.text.trim())
                      .filter(Boolean);
                    if (texts.length > 0) {
                      return { show: true, text: texts.join(" ") };
                    }
                  }
                  // Tool use results or other messages with a top-level "text" field
                  if (typeof parsed.text === "string" && parsed.text.trim()) {
                    return { show: true, text: parsed.text.trim() };
                  }
                  // JSON with no extractable human-readable content — suppress
                  return { show: false, text: "" };
                } catch {
                  // Not JSON — show as-is
                  return { show: true, text: line };
                }
              }

              function PlannerAgentCard({ agent, logLines, detailMessage }) {
                const [elapsed, setElapsed] = useState(agent.elapsed || 0);
                const logTailRef = useRef(null);
                useEffect(() => {
                  setElapsed(agent.elapsed || 0);
                }, [agent.elapsed]);
                useEffect(() => {
                  const timer = setInterval(() => setElapsed((prev) => prev + 1), 1000);
                  return () => clearInterval(timer);
                }, []);
                useEffect(() => {
                  if (logTailRef.current) {
                    logTailRef.current.scrollTop = logTailRef.current.scrollHeight;
                  }
                }, [logLines.length]);
                return (
                  html`<div style=${{
                    background: 'var(--bg-surface)',
                    border: '1px solid var(--border-medium)',
                    borderRadius: 'var(--radius-lg)',
                    padding: 'var(--space-4)',
                    display: 'flex',
                    flexDirection: 'column',
                    height: '280px',
                    minWidth: 0,
                  }}> <div style=${{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 'var(--space-2)', minWidth: 0 }}> <span class=${"mono"} style=${{ fontSize: 'var(--text-sm)', color: 'var(--status-active)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', minWidth: 0 }} title=${agent.file}> ${agent.file} </span> <span class=${"mono muted"} style=${{ fontSize: 'var(--text-xs)', flexShrink: 0, whiteSpace: 'nowrap', marginLeft: 'var(--space-2)' }}> ${formatElapsed(elapsed)} </span> </div> ${detailMessage ? (
                      html`<div class=${"detail-line"} style=${{
                        marginBottom: 'var(--space-2)',
                        padding: 'var(--space-1) var(--space-2)',
                        background: 'rgba(59, 130, 246, 0.08)',
                        borderRadius: 'var(--radius-sm)',
                        fontSize: 'var(--text-xs)',
                        color: 'var(--status-active)',
                        fontFamily: 'monospace',
                        overflow: 'hidden',
                        textOverflow: 'ellipsis',
                        whiteSpace: 'nowrap',
                      }}> ${detailMessage} </div>`
                    ) : null} <div ref=${logTailRef} class=${"log-tail"} style=${{ flex: 1, minHeight: 0, overflowY: 'auto', fontSize: 'var(--text-xs)' }}> ${logLines.length > 0
                        ? logLines.map(entry => filterLogLine(entry.line)).filter(r => r.show).slice(-10).map((r, idx) => (
                            html`<div key=${idx} class=${"log-line"}>${r.text}</div>`
                          ))
                        : html`<div class=${"log-line muted"}>Waiting for output...</div>`} </div> </div>`
                );
              }

              function PhaseActivityCard({ title, subtitle, statusLabel, events, pipeline, phaseLogs, planningAgents, taskLogs, detailMessage, phaseDetail }) {
                const totalIn = pipeline?.intake || 0;
                const claimed = pipeline?.planning || 0;
                const staged = pipeline?.staged || 0;
                const review = pipeline?.review || 0;
                const total = totalIn + claimed + staged + review;
                const processed = staged + review;
                const progressPct = total > 0 ? Math.round((processed / total) * 100) : 0;
                const logLines = phaseLogs || [];
                const logTailRef = useRef(null);
                const [elapsed, setElapsed] = useState(0);
                useEffect(() => {
                  const timer = setInterval(() => setElapsed((prev) => prev + 1), 1000);
                  return () => clearInterval(timer);
                }, []);
                useEffect(() => {
                  if (logTailRef.current) {
                    logTailRef.current.scrollTop = logTailRef.current.scrollHeight;
                  }
                }, [logLines.length]);
                return (
                  html`<article class=${"worker-card active"} style=${{ gridColumn: '1 / -1' }}> <div class=${"worker-card-header"}> <div class=${"worker-card-title"}> <span class=${"mono"} style=${{ color: 'var(--status-active)', fontSize: 'var(--text-md)' }}>${title}</span> <span class=${"secondary"}>${subtitle}</span> </div> <div style=${{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)' }}> <span class=${"mono muted"} style=${{ fontSize: 'var(--text-xs)' }}>${formatElapsed(elapsed)}</span> <span class=${"status-badge"} style=${statusBadgeStyle("active")}>${statusLabel}</span> </div> </div> ${total > 0 ? (
                      html`<div style=${{ marginTop: 'var(--space-3)' }}> <div style=${{ display: 'flex', justifyContent: 'space-between', marginBottom: '4px' }}> <span class=${"mono muted"} style=${{ fontSize: 'var(--text-xs)' }}>${`${processed}/${total} processed`}</span> <span class=${"mono muted"} style=${{ fontSize: 'var(--text-xs)' }}>${`${progressPct}%`}</span> </div> <div class=${"progress-bar"} style=${{ gridTemplateColumns: '1fr' }}> <span style=${{
                            background: 'var(--status-active)',
                            width: `${progressPct}%`,
                            transition: 'width 400ms ease',
                            display: 'block',
                          }} /> </div> </div>`
                    ) : null} ${detailMessage ? (
                      html`<div class=${"detail-line"} style=${{
                        marginTop: 'var(--space-2)',
                        padding: 'var(--space-1) var(--space-2)',
                        background: 'rgba(59, 130, 246, 0.08)',
                        borderRadius: 'var(--radius-sm)',
                        fontSize: 'var(--text-xs)',
                        color: 'var(--status-active)',
                        fontFamily: 'monospace',
                        overflow: 'hidden',
                        textOverflow: 'ellipsis',
                        whiteSpace: 'nowrap',
                      }}> ${detailMessage} </div>`
                    ) : null} ${(planningAgents || []).length > 0 ? (
                      html`<div style=${{ display: 'grid', gridTemplateColumns: `repeat(${Math.min((planningAgents || []).length, 4)}, minmax(0, 1fr))`, gap: 'var(--space-3)', marginTop: 'var(--space-3)' }}> ${(planningAgents || []).map((agent) => (
                          html`<${PlannerAgentCard} key=${agent.planner_task_id} agent=${agent} logLines=${(taskLogs || {})[agent.planner_task_id] || []} detailMessage=${(phaseDetail || {})[agent.planner_task_id]} />`
                        ))} </div>`
                    ) : (
                      html`<div ref=${logTailRef} class=${"log-tail"} style=${{ minHeight: '60px', maxHeight: '240px', overflowY: 'auto' }}> ${logLines.length > 0 ? (
                          logLines
                            .map(entry => filterLogLine(entry.line))
                            .filter(r => r.show)
                            .slice(-20)
                            .map((r, idx) => (
                              html`<div key=${idx} class=${"log-line"}>${r.text}</div>`
                            ))
                        ) : events.length === 0 ? (
                          html`<div class=${"log-line muted"}>Claude CLI running... (${formatElapsed(elapsed)})</div>`
                        ) : events.slice(-8).map((evt, idx) => (
                          html`<div key=${idx} class=${`log-line ${evt.type?.includes("error") ? "error" : evt.type?.includes("fail") ? "error" : ""}`}> <span class=${"muted"} style=${{ marginRight: '8px' }}>${evt.timestamp?.slice(11, 19) || ""}</span> ${evt.message} </div>`
                        ))} </div>`
                    )} </article>`
                );
              }

              function VerificationCard({ sessionStatus, runtimeState, effectiveConfig, recentEvents, taskLogs, onOpenTask }) {
                const isVerifying = sessionStatus === "verifying";
                const isAutoFix = sessionStatus === "auto_fixing";
                const reason = runtimeState.verification_reason;
                const attempt = runtimeState.auto_fix_attempt || 0;
                const maxAttempts = effectiveConfig.auto_fix?.max_attempts || 0;
                const fixContext = runtimeState.auto_fix_context;
                const fixTaskId = runtimeState.auto_fix_task_id;
                const lastSummary = runtimeState.last_fix_summary;

                // Live timer — syncs from server on each push, ticks locally between pushes
                const [elapsed, setElapsed] = useState(runtimeState.verification_elapsed || 0);
                const logTailRef = useRef(null);
                const [expanded, setExpanded] = useState(false);
                useEffect(() => {
                  setElapsed(runtimeState.verification_elapsed || 0);
                }, [runtimeState.verification_elapsed]);
                useEffect(() => {
                  if (!isVerifying && !isAutoFix) return;
                  const timer = setInterval(() => setElapsed(prev => prev + 1), 1000);
                  return () => clearInterval(timer);
                }, [isVerifying, isAutoFix]);

                // Auto-scroll log tail
                useEffect(() => {
                  if (logTailRef.current && !expanded) {
                    logTailRef.current.scrollTop = logTailRef.current.scrollHeight;
                  }
                });

                const reasonLabel = verificationReasonLabel(reason, sessionStatus);

                const borderColor = isAutoFix ? 'rgba(249, 115, 22, 0.4)' : 'rgba(245, 158, 11, 0.4)';
                const glowColor = isAutoFix ? 'rgba(249, 115, 22, 0.15)' : 'rgba(245, 158, 11, 0.15)';
                const accentColor = isAutoFix ? 'var(--status-review)' : 'var(--status-active)';

                // Streaming log lines from taskLogs
                const autoFixLines = (taskLogs || {})["__phase_auto_fix__"] || [];
                const verificationLines = (taskLogs || {})["__phase_verification__"] || [];
                const streamingLines = isAutoFix ? autoFixLines : verificationLines;
                const verificationStart = runtimeState?.verification_started_at;
                const eventLines = recentEvents.filter(e => {
                  const isRelevantType = e.type?.includes("verification") || e.type?.includes("auto_fix");
                  if (!isRelevantType) return false;
                  if (!verificationStart || !e.timestamp) return true;
                  return e.timestamp >= verificationStart;
                });
                const hasContent = streamingLines.length > 0 || eventLines.length > 0;

                return (
                  html`<article class=${"worker-card active"} style=${{
                    gridColumn: '1 / -1', borderColor, boxShadow: `0 0 12px ${glowColor}`,
                    cursor: 'pointer',
                  }} onClick=${() => setExpanded(e => !e)}> <div class=${"worker-card-header"}> <div class=${"worker-card-title"}> <span style=${{ color: accentColor, fontSize: 'var(--text-md)', fontWeight: 600 }}> ${reasonLabel} </span> ${fixContext === "task_failure" && fixTaskId ? (
                          html`<button type=${"button"} class=${"nav-link"} style=${{ padding: 0, fontSize: 'var(--text-xs)', textDecoration: 'underline' }} onClick=${(e) => { e.stopPropagation(); if (onOpenTask) onOpenTask(fixTaskId); }}> View task: ${fixTaskId} </button>`
                        ) : null} </div> <div style=${{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)' }}> <span class=${"mono muted"} style=${{ fontSize: 'var(--text-xs)' }}>${expanded ? "▲" : "▼"}</span> <span class=${"status-badge"} style=${statusBadgeStyle(isAutoFix ? "review" : "active")}> ${isAutoFix ? `attempt ${attempt}/${maxAttempts}` : "running"} </span> </div> </div> ${(isVerifying || isAutoFix) ? (
                      html`<div style=${{
                        display: 'flex', alignItems: 'center', gap: 'var(--space-2)',
                        marginTop: 'var(--space-2)',
                        fontSize: 'var(--text-xs)', color: 'var(--text-secondary)',
                      }}> <span class=${"mono muted"}>Elapsed:</span> <span class=${"mono"}>${formatElapsed(elapsed)}</span> </div>`
                    ) : null} ${isAutoFix && maxAttempts > 0 ? (
                      html`<div style=${{ marginTop: 'var(--space-3)' }}> <div style=${{ display: 'flex', justifyContent: 'space-between', marginBottom: '4px' }}> <span class=${"mono muted"} style=${{ fontSize: 'var(--text-xs)' }}> ${fixContext === "task_failure" && fixTaskId
                              ? `Fixing task: ${fixTaskId}`
                              : "Fixing verification failures"} </span> <span class=${"mono muted"} style=${{ fontSize: 'var(--text-xs)' }}> ${`${attempt}/${maxAttempts}`} </span> </div> <div class=${"progress-bar"} style=${{ gridTemplateColumns: `repeat(${maxAttempts}, 1fr)` }}> ${Array.from({ length: maxAttempts }).map((_, i) => (
                            html`<span key=${i} class=${i < attempt ? "done" : i === attempt ? "active" : "future"} />`
                          ))} </div> </div>`
                    ) : null} ${lastSummary ? (
                      html`<div style=${{
                        marginTop: 'var(--space-2)', padding: 'var(--space-2)',
                        background: 'var(--bg-surface)', borderRadius: '4px',
                        fontSize: 'var(--text-xs)', color: 'var(--text-secondary)',
                        fontFamily: 'var(--font-mono)',
                        maxHeight: '120px', overflowY: 'auto',
                      }}> <span class=${"muted"}>Last fix: </span>${lastSummary} </div>`
                    ) : null} ${expanded ? (
                      html`<div class=${"log-tail"} style=${{ maxHeight: '400px', minHeight: '200px', overflowY: 'auto' }}> ${eventLines.map((evt, idx) => (
                          html`<div key=${`evt-${idx}`} class=${`log-line ${evt.type?.includes("fail") ? "error" : ""}`} style=${{ whiteSpace: 'pre-wrap' }}> <span class=${"muted"} style=${{ marginRight: '8px' }}>${evt.timestamp?.slice(11, 19) || ""}</span> ${evt.message} </div>`
                        ))} ${streamingLines.map(entry => filterLogLine(entry.line)).filter(r => r.show).map((r, idx) => (
                          html`<div key=${`log-${idx}`} class=${"log-line"}>${r.text}</div>`
                        ))} ${!hasContent ? (
                          html`<div class=${"log-line muted"}> ${isVerifying ? "Running verification command..." : "Running auto-fix agent..."} </div>`
                        ) : null} </div>`
                    ) : (
                      html`<div ref=${logTailRef} class=${"log-tail"} style=${{ minHeight: '60px', maxHeight: '250px', overflowY: 'auto' }}> ${eventLines.slice(-6).map((evt, idx) => (
                          html`<div key=${`evt-${idx}`} class=${`log-line ${evt.type?.includes("fail") ? "error" : ""}`} style=${{ whiteSpace: 'pre-wrap' }}> <span class=${"muted"} style=${{ marginRight: '8px' }}>${evt.timestamp?.slice(11, 19) || ""}</span> ${evt.message} </div>`
                        ))} ${streamingLines.map(entry => filterLogLine(entry.line)).filter(r => r.show).slice(-15).map((r, idx) => (
                          html`<div key=${`log-${idx}`} class=${"log-line"}>${r.text}</div>`
                        ))} ${!hasContent ? (
                          html`<div class=${"log-line muted"}> ${isVerifying ? "Running verification command..." : "Running auto-fix agent..."} </div>`
                        ) : null} </div>`
                    )} </article>`
                );
              }

              function copyToClipboard(text, setCopied) {
                navigator.clipboard.writeText(text).then(() => {
                  if (setCopied) {
                    setCopied(true);
                    setTimeout(() => setCopied(false), 1500);
                  }
                }).catch(() => {});
              }

              function CompletionCard({ currentSession, tasks, pipeline, onCleanup }) {
                const env = currentSession?.config?.environment || {};
                const sourceRepo = env.COGNITIVE_SWITCHYARD_SOURCE_REPO || "";
                const worktreeRoot = env.COGNITIVE_SWITCHYARD_REPO_ROOT || "";
                const branch = env.COGNITIVE_SWITCHYARD_BRANCH || "";
                const hasWorktree = !!(sourceRepo && worktreeRoot && sourceRepo !== worktreeRoot);

                const doneTasks = (tasks || []).filter(t => t.status === "done");
                const sessionName = currentSession?.name || currentSession?.id || "session";
                const defaultCommitMsg = [
                  "feat: " + sessionName,
                  "",
                  "Implemented:",
                  ...doneTasks.map(t => "- [" + t.task_id + "] " + t.title),
                  ...(pipeline.blocked > 0 ? ["", "Blocked: " + pipeline.blocked + " task(s)"] : []),
                  "",
                  "Session: " + (currentSession?.id || ""),
                ].join("\\n");

                const [editableCommitMsg, setEditableCommitMsg] = useState(defaultCommitMsg);
                const [worktreeCleaned, setWorktreeCleaned] = useState(false);
                const [cleaningUp, setCleaningUp] = useState(false);
                const [copiedValidate, setCopiedValidate] = useState(false);
                const [copiedSquash, setCopiedSquash] = useState(false);
                const [copiedPr, setCopiedPr] = useState(false);
                const [copiedMsg, setCopiedMsg] = useState(false);

                const validateCmds = hasWorktree
                  ? "cd " + worktreeRoot + "\\ngit log --oneline\\ngit diff --stat HEAD~1"
                  : "";
                const squashCmds = hasWorktree
                  ? "cd " + sourceRepo + "\\ngit merge --squash " + branch + "\\ngit commit -m \\"" + editableCommitMsg.replace(/"/g, '\\\\"') + "\\""
                  : "";
                const prCmds = hasWorktree
                  ? "cd " + sourceRepo + "\\ngh pr create --head " + branch
                  : "";

                async function handleCleanup() {
                  if (!currentSession?.id) return;
                  const confirmed = window.confirm("Remove the worktree for this session? This cannot be undone.");
                  if (!confirmed) return;
                  setCleaningUp(true);
                  try {
                    await fetch("/api/sessions/" + currentSession.id + "/cleanup-worktree", { method: "POST" });
                    setWorktreeCleaned(true);
                    if (onCleanup) onCleanup();
                  } catch (e) {
                    alert("Cleanup failed: " + e.message);
                  } finally {
                    setCleaningUp(false);
                  }
                }

                return (
                  html`<section class=${"worker-grid"}> <article class=${"worker-card"} style=${{ gridColumn: "1 / -1", borderColor: "rgba(52, 211, 153, 0.3)" }}> <div class=${"worker-card-header"}> <div class=${"worker-card-title"}> <span class=${"mono"} style=${{ color: "var(--status-done)", fontSize: "var(--text-md)" }}> Session Completed — Next Steps </span> <span class=${"secondary"}> ${pipeline.done || 0} task(s) done${pipeline.blocked > 0 ? ", " + pipeline.blocked + " blocked" : ""} </span> </div> <span class=${"status-badge"} style=${{ background: "rgba(52, 211, 153, 0.15)", color: "var(--status-done)", border: "1px solid rgba(52, 211, 153, 0.3)" }}>completed</span> </div> ${hasWorktree && !worktreeCleaned ? (
                        html`<div> <div class=${"completion-card-section"}> <h4>1. Validate</h4> <div class=${"completion-code-block"}> ${validateCmds} <button type=${"button"} class=${"copy-btn"} onClick=${() => copyToClipboard(validateCmds, setCopiedValidate)}> ${copiedValidate ? "Copied!" : "Copy"} </button> </div> </div> <div class=${"completion-card-section"}> <h4>2. Commit message</h4> <textarea class=${"commit-msg-textarea"} value=${editableCommitMsg} onInput=${e => setEditableCommitMsg(e.target.value)} rows=${8} /> <button type=${"button"} class=${"secondary-button"} style=${{ marginTop: "var(--space-2)", fontSize: "var(--text-xs)" }} onClick=${() => copyToClipboard(editableCommitMsg, setCopiedMsg)}> ${copiedMsg ? "Copied!" : "Copy message"} </button> </div> <div class=${"completion-card-section"}> <h4>3a. Squash merge into upstream</h4> <div class=${"completion-code-block"}> ${"cd " + sourceRepo + "\\ngit merge --squash " + branch + "\\ngit commit"} <button type=${"button"} class=${"copy-btn"} onClick=${() => copyToClipboard("cd " + sourceRepo + "\\ngit merge --squash " + branch + "\\ngit commit", setCopiedSquash)}> ${copiedSquash ? "Copied!" : "Copy"} </button> </div> </div> <div class=${"completion-card-section"}> <h4>3b. Open a pull request</h4> <div class=${"completion-code-block"}> ${prCmds} <button type=${"button"} class=${"copy-btn"} onClick=${() => copyToClipboard(prCmds, setCopiedPr)}> ${copiedPr ? "Copied!" : "Copy"} </button> </div> </div> <div class=${"completion-card-section"}> <button type=${"button"} class=${"secondary-button"} style=${{ fontSize: "var(--text-xs)", color: "var(--text-muted)" }} disabled=${cleaningUp} onClick=${handleCleanup}> ${cleaningUp ? "Cleaning up..." : "Clean up worktree"} </button> </div> </div>`
                      ) : hasWorktree && worktreeCleaned ? (
                        html`<div class=${"completion-card-section"}> <span class=${"mono muted"} style=${{ fontSize: "var(--text-sm)" }}>Worktree cleaned up.</span> </div>`
                      ) : (
                        html`<div class=${"completion-card-section"}> <span style=${{ color: "var(--text-secondary)", fontSize: "var(--text-sm)" }}> Session output is in:${" "} <span class=${"mono"} style=${{ fontSize: "var(--text-xs)" }}>${currentSession?.id || ""}</span> </span> </div>`
                      )} </article> </section>`
                );
              }

              const TASK_TRANSITIONS = {
                blocked: [
                  { target: "ready", label: "Retry", icon: "refresh-cw" },
                  { target: "intake", label: "Re-plan", icon: "edit" },
                ],
                review: [
                  { target: "intake", label: "Re-plan", icon: "edit" },
                  { target: "ready", label: "Approve & Queue", icon: "check-circle" },
                ],
                done: [
                  { target: "intake", label: "Re-plan", icon: "edit" },
                  { target: "ready", label: "Re-execute", icon: "refresh-cw" },
                ],
                staged: [
                  { target: "intake", label: "Re-plan", icon: "edit" },
                  { target: "review", label: "Send to Review", icon: "eye" },
                ],
                planning: [
                  { target: "intake", label: "Re-plan", icon: "edit" },
                ],
              };

              function MonitorView({ dashboard, currentSession, tasks, taskLogs, phaseDetail, onOpenTask, onOpenDag, onRevealFile, onMoveTask, onRescan, isRescanning, onReprocess, isReprocessing }) {
                const pipeline = dashboard?.pipeline || {};
                const pipelineDirs = dashboard?.pipeline_dirs || {};
                const workers = dashboard?.workers || [];
                const recentEvents = dashboard?.recent_events || [];
                const sessionStatus = dashboard?.session?.status || currentSession?.status || "created";
                const runtimeState = dashboard?.runtime_state || {};
                const effectiveConfig = dashboard?.effective_runtime_config || {};
                const isPreExecution = ["planning", "resolving"].includes(sessionStatus);
                const isExecution = ["running", "paused", "verifying", "auto_fixing"].includes(sessionStatus);
                const isTerminal = ["completed", "aborted"].includes(sessionStatus);
                const canReprocess = currentSession
                  && ["created", "idle", "paused"].includes(sessionStatus)
                  && !isReprocessing
                  && !currentSession.workers?.some(w => w.status === "active")
                  && ((pipeline.intake || 0) + (pipeline.staged || 0) + (pipeline.ready || 0)) > 0;

                return (
                  html`<div> <${PipelineStrip} pipeline=${pipeline} pipelineDirs=${pipelineDirs} sessionStatus=${sessionStatus} currentSession=${currentSession} onRevealFile=${onRevealFile} onOpenDag=${onOpenDag} onRescan=${onRescan} isRescanning=${isRescanning} onReprocess=${onReprocess} isReprocessing=${isReprocessing} canReprocess=${canReprocess} /> <${HealthSummaryBar} tasks=${tasks} workers=${workers} /> ${recentEvents.length > 0 ? (
                      html`<div class=${"event-feed"}> ${recentEvents.map((evt, idx) => (
                          html`<div key=${idx} class=${`event-row ${evt.type === "session_error" ? "error" : evt.type === "pipeline_stopped" ? "warning" : ""}`}> <span class=${"mono muted"} style=${{ fontSize: 'var(--text-xs)' }}>${evt.timestamp?.slice(11, 19) || ""}</span> <span class=${"mono"} style=${{ fontSize: 'var(--text-xs)', color: evt.type === "session_error" ? "var(--status-blocked)" : evt.type === "pipeline_stopped" ? "var(--status-review)" : "var(--text-secondary)" }}> ${evt.type} </span> <span style=${{ fontSize: 'var(--text-sm)', flex: 1, minWidth: 0, wordBreak: 'break-word', whiteSpace: 'pre-wrap' }}>${evt.message}</span> </div>`
                        ))} </div>`
                    ) : null} <main class=${"page"}> ${isPreExecution ? (
                        html`<section class=${"worker-grid"}> <${PhaseActivityCard} title=${sessionStatus === "planning" ? "Planning Phase" : "Resolution Phase"} subtitle=${sessionStatus === "planning"
                              ? `Analyzing intake items and generating task plans (${pipeline.planning || 0} claimed, ${pipeline.staged || 0} staged, ${pipeline.review || 0} to review)`
                              : `Resolving dependencies and ordering tasks (${pipeline.staged || 0} staged plans)`} statusLabel=${sessionStatus} events=${recentEvents} pipeline=${pipeline} phaseLogs=${taskLogs[sessionStatus === "planning" ? "__phase_planning__" : "__phase_resolution__"] || []} planningAgents=${sessionStatus === "planning" ? (dashboard?.planning_agents || []) : []} taskLogs=${taskLogs} detailMessage=${phaseDetail[sessionStatus === "planning" ? "__phase_planning__" : "__phase_resolution__"]} phaseDetail=${phaseDetail} /> ${pipeline.review > 0 ? (
                            html`<article class=${"worker-card"} style=${{
                              borderColor: 'rgba(249, 115, 22, 0.4)',
                              boxShadow: '0 0 12px rgba(249, 115, 22, 0.15)',
                            }}> <div class=${"worker-card-header"}> <div class=${"worker-card-title"}> <span class=${"mono"} style=${{ color: 'var(--status-review)', fontSize: 'var(--text-md)' }}>Items in Review</span> <span class=${"secondary"}>${`${pipeline.review} item(s) need human review before proceeding`}</span> </div> <span class=${"status-badge"} style=${statusBadgeStyle("review")}>${pipeline.review}</span> </div> <div class=${"log-tail"} style=${{ minHeight: '40px' }}> <div class=${"log-line"}> <button type=${"button"} class=${"nav-link"} onClick=${() => pipelineDirs.review && onRevealFile(pipelineDirs.review)} style=${{ textDecoration: 'underline', padding: 0 }}> Open review directory to inspect </button> </div> </div> </article>`
                          ) : null} </section>`
                      ) : null} ${isExecution ? (
                        html`<${preact.Fragment}> ${sessionStatus === "verifying" || sessionStatus === "auto_fixing" ? (
                            html`<section class=${"worker-grid"} style=${{ marginBottom: 'var(--space-4)' }}> <${VerificationCard} sessionStatus=${sessionStatus} runtimeState=${runtimeState} effectiveConfig=${effectiveConfig} recentEvents=${recentEvents} taskLogs=${taskLogs} onOpenTask=${onOpenTask} /> </section>`
                          ) : null} ${sessionStatus === "running" && effectiveConfig.verification_interval > 0 ? (
                            runtimeState.verification_pending ? (
                              html`<div class=${"verification-countdown"} style=${{
                                display: 'flex', alignItems: 'center', gap: 'var(--space-2)',
                                padding: 'var(--space-2) var(--space-3)',
                                marginBottom: 'var(--space-3)',
                                background: 'rgba(245, 158, 11, 0.1)', borderRadius: '6px',
                                border: '1px solid rgba(245, 158, 11, 0.3)',
                                fontSize: 'var(--text-xs)',
                              }}> <span class=${"mono"} style=${{ color: 'var(--status-active)' }}> ${`Verification pending: ${verificationReasonLabel(runtimeState.verification_reason, sessionStatus)}`} </span> </div>`
                            ) : (
                              html`<div class=${"verification-countdown"} style=${{
                                display: 'flex', alignItems: 'center', gap: 'var(--space-2)',
                                padding: 'var(--space-2) var(--space-3)',
                                marginBottom: 'var(--space-3)',
                                background: 'var(--bg-elevated)', borderRadius: '6px',
                                border: '1px solid var(--border-subtle)',
                                fontSize: 'var(--text-xs)',
                              }}> <span class=${"mono muted"}>Next verification:</span> <span class=${"mono"} style=${{ color: 'var(--status-active)' }}> ${`${runtimeState.completed_since_verification || 0} / ${effectiveConfig.verification_interval} tasks`} </span> <div style=${{
                                  flex: 1, height: '4px', background: 'var(--border-subtle)',
                                  borderRadius: '2px', overflow: 'hidden',
                                }}> <div style=${{
                                    width: `${Math.min(100, ((runtimeState.completed_since_verification || 0) / effectiveConfig.verification_interval) * 100)}%`,
                                    height: '100%', background: 'var(--status-active)',
                                    transition: 'width 400ms ease',
                                  }} /> </div> </div>`
                            )
                          ) : null} ${runtimeState.last_verification_test_summary ? (
                            html`<div style=${{
                              display: 'flex', alignItems: 'center', gap: 'var(--space-2)',
                              padding: 'var(--space-2) var(--space-3)',
                              marginBottom: 'var(--space-3)',
                              background: 'rgba(34, 197, 94, 0.08)', borderRadius: '6px',
                              border: '1px solid rgba(34, 197, 94, 0.25)',
                              fontSize: 'var(--text-xs)',
                            }}> <span style=${{ color: 'rgb(34, 197, 94)', fontSize: '12px' }}>✓</span> <span class=${"mono"} style=${{ color: 'rgb(34, 197, 94)' }}> ${runtimeState.last_verification_test_summary} </span> </div>`
                          ) : null} <section class=${"worker-grid"}> ${workers.map((worker, index) => {
                              const lineTail = (() => {
                                if (worker.task_id && taskLogs[worker.task_id]?.length) {
                                  return taskLogs[worker.task_id].map((entry) => ({ line: entry.line, ts: entry.ts }));
                                }
                                if (worker.last_log_line) {
                                  return [{ line: worker.last_log_line, ts: null }];
                                }
                                return [{ line: "Waiting for task...", ts: null }];
                              })();
                              const phaseTotal = Math.max(1, Number(worker.phase_total) || 1);
                              const currentIndex = Math.max(0, (Number(worker.phase_num) || 1) - 1);
                              const isIdleWarning = worker.status === "active"
                                && worker.task_idle_limit > 0
                                && (worker.last_activity_ago || 0) >= (worker.task_idle_limit * 2) / 3;
                              const stateClass = isIdleWarning
                                ? "worker-card warning"
                                : worker.status === "active"
                                  ? "worker-card active"
                                  : worker.status === "problem"
                                    ? "worker-card problem"
                                    : "worker-card idle";
                              return (
                                html`<article key=${worker.slot} class=${stateClass} onClick=${() => worker.task_id && onOpenTask(worker.task_id)} style=${{ animationDelay: `${160 + index * 60}ms` }}> <div class=${"worker-card-header"}> <div class=${"worker-card-title"}> <span class=${"mono muted"}>${`slot ${worker.slot}`}</span> <span class=${"mono"}>${worker.task_id || "idle"}</span> <span class=${"secondary"}>${worker.task_title || "Waiting for task..."}</span> </div> <span class=${"status-badge"} style=${statusBadgeStyle(isIdleWarning ? "warning" : worker.status)}> ${isIdleWarning ? "warning" : worker.status} </span> </div> ${worker.status !== "idle" ? (
                                    html`<${preact.Fragment}> <div class=${"progress-bar"} style=${{ gridTemplateColumns: `repeat(${phaseTotal}, 1fr)` }}> ${Array.from({ length: phaseTotal }).map((_, phaseIndex) => {
                                          let phaseClass = "future";
                                          if (phaseIndex < currentIndex) {
                                            phaseClass = "done";
                                          } else if (phaseIndex === currentIndex && worker.status === "active") {
                                            phaseClass = "active";
                                          }
                                          return html`<span key=${phaseIndex} class=${phaseClass} />`;
                                        })} </div> ${worker.detail ? html`<div class=${"detail-line"}>${worker.detail}</div>` : null} <div class=${"detail-line muted"} style=${{ display: 'flex', alignItems: 'center', gap: '8px' }}> <span>${formatElapsed(worker.elapsed || 0)}</span> <${LastActivityIndicator} worker=${worker} /> </div> <div class=${"log-tail"}> ${lineTail.map(e => ({ ...filterLogLine(e.line), ts: e.ts })).filter(r => r.show).slice(-5).map((r, lineIndex) => (
                                          html`<div key=${lineIndex} class=${"log-line"}> ${r.ts ? html`<span class=${"mono muted"} style=${{ marginRight: '6px', fontSize: 'var(--text-xs)' }}>${r.ts.slice(11, 19)}</span>` : null} ${r.text} </div>`
                                        ))} </div> <//>`
                                  ) : null} </article>`
                              );
                            })} </section> <//>`
                      ) : null} ${isTerminal ? (
                        sessionStatus === "completed" ? (
                          html`<${CompletionCard} currentSession=${currentSession} tasks=${tasks} pipeline=${pipeline} />`
                        ) : (
                          html`<section class=${"worker-grid"}> <article class=${"worker-card"} style=${{
                              gridColumn: '1 / -1',
                              borderColor: 'rgba(239, 68, 68, 0.3)',
                            }}> <div class=${"worker-card-header"}> <div class=${"worker-card-title"}> <span class=${"mono"} style=${{
                                    color: 'var(--status-blocked)',
                                    fontSize: 'var(--text-md)',
                                  }}> Session Aborted </span> <span class=${"secondary"}> ${`${pipeline.done || 0} tasks completed, ${pipeline.blocked || 0} blocked`} </span> </div> <span class=${"status-badge"} style=${statusBadgeStyle(sessionStatus)}>${sessionStatus}</span> </div> </article> </section>`
                        )
                      ) : null} ${!isPreExecution && !isExecution && !isTerminal && sessionStatus === "created" ? (
                        html`<div class=${"empty-state"}> Session created but not yet started. Go to Setup to configure and start. </div>`
                      ) : null} ${pipeline.review > 0 && isExecution ? (
                        html`<article class=${"worker-card"} style=${{
                          marginTop: 'var(--space-4)',
                          borderColor: 'rgba(249, 115, 22, 0.4)',
                          boxShadow: '0 0 12px rgba(249, 115, 22, 0.15)',
                        }}> <div class=${"worker-card-header"}> <div class=${"worker-card-title"}> <span class=${"mono"} style=${{ color: 'var(--status-review)' }}>Items in Review</span> <span class=${"secondary"}>${`${pipeline.review} item(s) parked for human review`}</span> </div> <button type=${"button"} class=${"secondary-button"} onClick=${() => pipelineDirs.review && onRevealFile(pipelineDirs.review)}> Open Review </button> </div> </article>`
                      ) : null} <section class=${"task-feed"}> ${tasks.length === 0 && isPreExecution ? (
                          html`<div class=${"empty-state muted"} style=${{ padding: 'var(--space-4)' }}> Tasks will appear here once planning completes and resolution assigns execution order. </div>`
                        ) : tasks.length === 0 ? (
                          html`<div class=${"empty-state"}>No tasks in this session yet.</div>`
                        ) : tasks.map((task) => (
                          html`<div key=${task.task_id} class=${`task-row ${task.status === "blocked" ? "blocked" : task.status === "active" ? "active" : ""}`} onClick=${() => onOpenTask(task.task_id)}> <div style=${{ display: 'flex', alignItems: 'center', gap: '8px', width: '100%' }}> <span class=${"mono"}>${task.task_id}</span> <span class=${"secondary task-title"}>${task.title}</span> ${(task.depends_on || []).length > 0 ? icon("link", { width: 12, height: 12 }) : null} ${(task.anti_affinity || []).length > 0 ? icon("shield", { width: 12, height: 12 }) : null} ${task.full_test_after ? (
                                html`<span title=${"Full test after completion"} style=${{
                                  fontSize: 'var(--text-xs)',
                                  color: 'var(--status-active)',
                                  fontWeight: 600,
                                  padding: '0 4px',
                                  background: 'rgba(245, 158, 11, 0.15)',
                                  borderRadius: '3px',
                                }}>FTA</span>`
                              ) : null} ${task.started_at ? (
                                html`<span class=${"mono muted"} style=${{ fontSize: 'var(--text-xs)' }}> ${task.started_at.slice(11, 19)} </span>`
                              ) : null} <span class=${"status-badge"} style=${statusBadgeStyle(task.status)}>${task.status}</span> <${TaskRowElapsed} task=${task} /> <div class=${"task-actions"} onClick=${(e) => e.stopPropagation()}> ${(TASK_TRANSITIONS[task.status] || []).map(({ target, label, icon: iconName }) => (
                                  html`<button key=${target} type=${"button"} class=${"icon-button"} title=${`${label} (\u2192 ${target})`} onClick=${() => onMoveTask(task.task_id, target)}> ${icon(iconName, { width: 14, height: 14 })} </button>`
                                ))} <button type=${"button"} class=${"icon-button"} title=${"Reveal plan file"} onClick=${() => onRevealFile(task.plan_path)}> ${icon("file-text", { width: 14, height: 14 })} </button> </div> </div> ${(() => {
                              const evts = task.events || [];
                              const last = evts.length ? evts[evts.length - 1] : null;
                              if (!last || !["task.blocked", "session_error"].includes(last.type)) return null;
                              const color = "var(--status-blocked)";
                              return (
                                html`<div style=${{ fontSize: 'var(--text-xs)', color, marginTop: '2px', paddingLeft: '2px' }}> ${last.message} </div>`
                              );
                            })()} </div>`
                        ))} </section> </main> </div>`
                );
              }

              function SetupView({
                currentSession,
                setupDraft,
                setSetupDraft,
                selectedPack,
                packs,
                intake,
                preflight,
                settings,
                showAdvanced,
                setShowAdvanced,
                isBusy,
                repoRootInfo,
                repoBranches,
                onCreateDraft,
                onStartSession,
                onRefreshIntake,
                onRunPreflight,
                onOpenIntake,
                onOpenIntakeTerminal,
                onRevealFile,
                onBrowseRepoRoot,
                onBrowseProjectDir,
                onResolveRepoRoot,
                onCreateBranch,
                onDiscardDraft,
                onNewRun,
                onNavigate
              }) {
                const sessionStatus = currentSession?.status || "none";
                const draftExists = sessionStatus === "created";
                const sessionActive = ACTIVE_STATUSES.has(sessionStatus) && sessionStatus !== "idle";
                const formLocked = draftExists || sessionActive || sessionStatus === "idle";
                const files = intake?.files || [];
                const packSupportsPlanning = Boolean(selectedPack?.planning_enabled);
                const packSupportsVerification = Boolean(selectedPack?.verification_enabled);
                const isIdle = sessionStatus === "idle";
                const canManageIntake = draftExists || isIdle;
                const canStart = draftExists && files.length > 0 && (preflight?.ok ?? false);
                const [newBranchName, setNewBranchName] = useState("");
                const [creatingBranch, setCreatingBranch] = useState(false);
                const showBranchSelector = repoRootInfo && repoRootInfo.is_git && repoBranches.length > 0;
                const showNewBranchInput = setupDraft.branch === "__new__";
                if (sessionActive) {
                  return (
                    html`<div class=${"setup-shell"}> <section class=${"setup-card"} style=${{ textAlign: 'center' }}> <h1 class=${"view-title"}>Session Active</h1> <p class=${"secondary"} style=${{ marginBottom: 'var(--space-6)' }}> ${`Session "${currentSession?.name}" is ${sessionStatus}. Configuration is locked while a session is running.`} </p> <button type=${"button"} class=${"action-button"} onClick=${() => onNavigate("monitor")}> Go to Monitor </button> </section> </div>`
                  );
                }
                return (
                  html`<div class=${"setup-shell"}> <section class=${"setup-card"}> <div class=${"row"} style=${{ justifyContent: 'space-between', alignItems: 'center' }}> <h1 class=${"view-title"} style=${{ margin: 0 }}> ${currentSession ? `Session: ${currentSession.name}` : "Configure Session"} </h1> ${draftExists ? (
                          html`<button type=${"button"} class=${"secondary-button"} style=${{ color: '#ef4444' }} disabled=${isBusy} onClick=${onDiscardDraft}>Reset</button>`
                        ) : null} </div> ${draftExists ? (
                        html`<div class=${"field-hint"} style=${{ marginBottom: '0.75rem' }}> ${`Pack: ${currentSession.pack} | ID: ${currentSession.id} | Configuration is locked. Drop intake files, run preflight, then start.`} </div>`
                      ) : isIdle ? (
                        html`<div class=${"field-hint"} style=${{ marginBottom: '0.75rem' }}> ${`Pack: ${currentSession.pack} | ID: ${currentSession.id} | Session idle — drop intake files and start a new run.`} </div>`
                      ) : null} <div class=${"form-grid"}> <div> <label class=${"field-label"}>Repository Root</label> <div class=${"row"} style=${{ gap: '0.5rem' }}> <input class=${"text-input"} style=${{ flex: 1 }} placeholder=${"/path/to/your/project"} value=${setupDraft.repo_root} disabled=${draftExists} onInput=${(event) => setSetupDraft((draft) => ({ ...draft, repo_root: event.target.value }))} onBlur=${() => onResolveRepoRoot(setupDraft.repo_root)} onKeyDown=${(event) => { if (event.key === 'Enter') onResolveRepoRoot(setupDraft.repo_root); }} /> <button type=${"button"} class=${"secondary-button"} disabled=${draftExists || isBusy} onClick=${onBrowseRepoRoot}>Browse</button> </div> ${repoRootInfo && repoRootInfo.exists && repoRootInfo.is_git ? (
                            html`<div class=${"field-hint"} style=${{ color: repoRootInfo.on_protected_branch ? '#f59e0b' : '#10b981' }}> ${repoRootInfo.on_protected_branch
                                ? `\u26a0 Git repository on branch ${repoRootInfo.branch} (protected \u2014 use a feature branch)`
                                : `\u2713 Git repository on branch ${repoRootInfo.branch}`} </div>`
                          ) : repoRootInfo && repoRootInfo.exists && !repoRootInfo.is_git ? (
                            html`<div class=${"field-hint"} style=${{ color: '#ef4444' }}> Directory exists but is not a git repository </div>`
                          ) : repoRootInfo && !repoRootInfo.exists ? (
                            html`<div class=${"field-hint"} style=${{ color: '#ef4444' }}> Directory does not exist </div>`
                          ) : null} ${draftExists && currentSession?.config?.environment?.COGNITIVE_SWITCHYARD_SOURCE_REPO ? (
                            html`<div class=${"field-hint"} style=${{ marginTop: '0.25rem' }}> ${`Session worktree: ${currentSession.config.environment.COGNITIVE_SWITCHYARD_REPO_ROOT}`} <br /> ${`Source repo: ${currentSession.config.environment.COGNITIVE_SWITCHYARD_SOURCE_REPO}`} </div>`
                          ) : null} </div> <div> <label class=${"field-label"}>Project Directory</label> <div class=${"row"} style=${{ gap: '0.5rem' }}> <input class=${"text-input"} style=${{ flex: 1 }} placeholder=${"e.g. cognitive_switchyard (optional — for monorepos)"} value=${setupDraft.project_dir} disabled=${draftExists} onInput=${(event) => setSetupDraft((draft) => ({ ...draft, project_dir: event.target.value }))} /> <button type=${"button"} class=${"secondary-button"} disabled=${draftExists || isBusy || !setupDraft.repo_root} onClick=${onBrowseProjectDir}>Browse</button> </div> <div class=${"field-hint"}> For monorepos, browse to the subdirectory so verification scopes to this project only. </div> </div> ${showBranchSelector ? (
                          html`<div> <label class=${"field-label"}>Branch</label> ${showNewBranchInput ? (
                              html`<div class=${"row"} style=${{ gap: '0.5rem' }}> <input class=${"text-input"} style=${{ flex: 1 }} placeholder=${"new-branch-name"} value=${newBranchName} disabled=${draftExists || creatingBranch} onInput=${(event) => setNewBranchName(event.target.value)} /> <button type=${"button"} class=${"secondary-button"} disabled=${draftExists || creatingBranch || !newBranchName.trim()} onClick=${async () => {
                                    setCreatingBranch(true);
                                    try {
                                      await onCreateBranch(setupDraft.repo_root, newBranchName.trim(), repoRootInfo.branch || "main");
                                      setNewBranchName("");
                                    } catch {
                                    } finally {
                                      setCreatingBranch(false);
                                    }
                                  }}>Create</button> <button type=${"button"} class=${"secondary-button"} disabled=${creatingBranch} onClick=${() => {
                                    setSetupDraft((draft) => ({ ...draft, branch: repoRootInfo?.branch || repoBranches[0] || "" }));
                                    setNewBranchName("");
                                  }}>Cancel</button> </div>`
                            ) : (
                              html`<select class=${"select-input"} value=${setupDraft.branch} disabled=${draftExists} onInput=${(event) => setSetupDraft((draft) => ({ ...draft, branch: event.target.value }))}> ${repoBranches.map((b) => html`<option key=${b} value=${b}>${b}</option>`)} <option value=${"__new__"}>New Branch...</option> </select>`
                            )} </div>`
                        ) : null} <div> <label class=${"field-label"}>Pack</label> <select class=${"select-input"} value=${setupDraft.pack} disabled=${draftExists} onInput=${(event) => setSetupDraft((draft) => ({ ...draft, pack: event.target.value }))}> ${packs.map((pack) => html`<option key=${pack.name} value=${pack.name}>${pack.name}</option>`)} </select> ${selectedPack ? html`<div class=${"field-hint"}>${selectedPack.description}</div>` : null} </div> <div> <label class=${"field-label"}>Session Name</label> <input class=${"text-input"} value=${setupDraft.name} disabled=${draftExists} onInput=${(event) => setSetupDraft((draft) => ({ ...draft, name: event.target.value }))} /> </div> <div> <label class=${"field-label"}>Session ID</label> <input class=${"text-input"} value=${setupDraft.id} disabled=${draftExists} onInput=${(event) => setSetupDraft((draft) => ({ ...draft, id: event.target.value }))} /> </div> <div class=${"row"}> ${packSupportsPlanning ? (
                            html`<div style=${{ flex: 1 }}> <label class=${"field-label"}>Planner Count</label> <input class=${"text-input"} type=${"number"} min=${"1"} max=${selectedPack?.max_planners || 99} disabled=${draftExists} value=${setupDraft.planner_count} onInput=${(event) => setSetupDraft((draft) => ({ ...draft, planner_count: event.target.value }))} /> ${selectedPack?.max_planners && parseInt(setupDraft.planner_count, 10) > selectedPack.max_planners ? (
                                html`<div class=${"field-hint"} style=${{ color: '#f59e0b' }}> ${`Pack limit: ${selectedPack.max_planners} — value will be clamped`} </div>`
                              ) : null} </div>`
                          ) : null} <div style=${{ flex: 1 }}> <label class=${"field-label"}>Worker Count</label> <input class=${"text-input"} type=${"number"} min=${"1"} max=${selectedPack?.max_workers || 99} disabled=${draftExists} value=${setupDraft.worker_count} onInput=${(event) => setSetupDraft((draft) => ({ ...draft, worker_count: event.target.value }))} /> ${selectedPack?.max_workers && parseInt(setupDraft.worker_count, 10) > selectedPack.max_workers ? (
                              html`<div class=${"field-hint"} style=${{ color: '#f59e0b' }}> ${`Pack limit: ${selectedPack.max_workers} — value will be clamped`} </div>`
                            ) : null} </div> ${packSupportsVerification ? (
                            html`<div style=${{ flex: 1 }}> <label class=${"field-label"}>Verification Interval</label> <input class=${"text-input"} type=${"number"} min=${"1"} placeholder=${selectedPack ? `pack default (${selectedPack.verification_interval})` : "pack default"} disabled=${draftExists} value=${setupDraft.verification_interval} onInput=${(event) => setSetupDraft((draft) => ({ ...draft, verification_interval: event.target.value }))} /> </div>`
                          ) : null} </div> <div> <label class=${"field-label"}>Defaults</label> <div class=${"field-hint"}> ${`pack=${settings?.default_pack || "n/a"} planners=${settings?.default_planners || 0} workers=${settings?.default_workers || 0} retention=${settings?.retention_days ?? 0}d`} </div> </div> <div class=${"action-row"}> <button type=${"button"} class=${"secondary-button"} onClick=${() => setShowAdvanced((value) => !value)}> ${showAdvanced ? "Hide Advanced" : "Show Advanced"} </button> ${canManageIntake ? (
                            html` <button type=${"button"} class=${"secondary-button"} onClick=${onOpenIntake}> Open Intake </button> <button type=${"button"} class=${"secondary-button"} onClick=${onOpenIntakeTerminal}> Intake Terminal </button> <button type=${"button"} class=${"secondary-button"} onClick=${onRefreshIntake}> Refresh Intake </button> ${draftExists ? (
                                html`<button type=${"button"} class=${"secondary-button"} disabled=${isBusy} onClick=${onRunPreflight}> ${isBusy ? "Running Preflight..." : preflight ? "Re-run Preflight" : "Run Preflight"} </button>`
                              ) : null} `
                          ) : null} </div> ${showAdvanced ? (
                          html`<div class=${"advanced-panel stack"}> <div class=${"row"}> <div style=${{ flex: 1 }}> <label class=${"field-label"}>Auto-Fix</label> <select class=${"select-input"} disabled=${draftExists} value=${setupDraft.auto_fix_enabled} onInput=${(event) => setSetupDraft((draft) => ({
                                    ...draft,
                                    auto_fix_enabled: event.target.value
                                  }))}> <option value=${""}>${selectedPack ? `Pack default (${selectedPack.auto_fix_enabled ? "Enabled" : "Disabled"})` : "Pack default"}</option> <option value=${"enabled"}>Enabled</option> <option value=${"disabled"}>Disabled</option> </select> </div> <div style=${{ flex: 1 }}> <label class=${"field-label"}>Auto-Fix Attempts</label> <input class=${"text-input"} type=${"number"} min=${"1"} placeholder=${selectedPack ? `pack default (${selectedPack.auto_fix_max_attempts})` : "pack default"} disabled=${draftExists} value=${setupDraft.auto_fix_max_attempts} onInput=${(event) => setSetupDraft((draft) => ({
                                    ...draft,
                                    auto_fix_max_attempts: event.target.value
                                  }))} /> </div> <div style=${{ flex: 1 }}> <label class=${"field-label"}>Poll Interval</label> <input class=${"text-input"} type=${"number"} step=${"0.01"} min=${"0.01"} disabled=${draftExists} value=${setupDraft.poll_interval} onInput=${(event) => setSetupDraft((draft) => ({
                                    ...draft,
                                    poll_interval: event.target.value
                                  }))} /> </div> </div> <div class=${"row"}> <div style=${{ flex: 1 }}> <label class=${"field-label"}>Task Idle Timeout (s)</label> <input class=${"text-input"} type=${"number"} min=${"0"} placeholder=${"pack default"} disabled=${draftExists} value=${setupDraft.task_idle_timeout} onInput=${(event) => setSetupDraft((draft) => ({
                                    ...draft,
                                    task_idle_timeout: event.target.value
                                  }))} /> </div> <div style=${{ flex: 1 }}> <label class=${"field-label"}>Task Max Timeout (s)</label> <input class=${"text-input"} type=${"number"} min=${"0"} placeholder=${"0 = no limit"} disabled=${draftExists} value=${setupDraft.task_max_timeout} onInput=${(event) => setSetupDraft((draft) => ({
                                    ...draft,
                                    task_max_timeout: event.target.value
                                  }))} /> </div> <div style=${{ flex: 1 }}> <label class=${"field-label"}>Session Max Timeout (s)</label> <input class=${"text-input"} type=${"number"} min=${"0"} placeholder=${"pack default"} disabled=${draftExists} value=${setupDraft.session_max_timeout} onInput=${(event) => setSetupDraft((draft) => ({
                                    ...draft,
                                    session_max_timeout: event.target.value
                                  }))} /> </div> </div> </div>`
                        ) : null} <div> <label class=${"field-label"}>Intake Directory</label> <div class=${"field-hint"} style=${{ fontFamily: 'monospace', fontSize: '0.8rem' }}> ${currentSession
                              ? `${settings?.runtime_root || "~/.cognitive_switchyard"}/sessions/${currentSession.id}/intake/`
                              : "Create a draft session to materialize the intake directory."} </div> <div class=${"intake-list"}> ${intake?.locked ? (
                              html`<div class=${"field-hint"}>Session locked - intake closed.</div>`
                            ) : null} ${files.length === 0 ? (
                              html`<div class=${"muted"}>Drop .md files into the intake directory to begin.</div>`
                            ) : files.map((file) => (
                              html`<div key=${file.path} class=${"intake-row"}> <div class=${"stack"} style=${{ gap: "4px" }}> <div class=${"row"} style=${{ gap: "8px" }}> ${icon("file-text", { width: 14, height: 14 })} <span class=${"mono"}>${file.filename}</span> ${file.in_snapshot === false ? html`<span class=${"muted"}>Not in session</span>` : null} </div> <div class=${"field-hint"}>${`${file.size} bytes | ${file.detected_at}`}</div> </div> ${!intake?.locked ? (
                                  html`<button type=${"button"} class=${"icon-button"} onClick=${() => onRevealFile(file.path)} aria-label=${`Reveal ${file.filename}`}> ${icon("folder-open", { width: 16, height: 16 })} </button>`
                                ) : null} </div>`
                            ))} </div> </div> <div> <label class=${"field-label"}> Preflight Checks ${preflight ? (
                              html`<span class=${"status-badge"} style=${{ ...statusBadgeStyle(preflight.ok ? "done" : "blocked"), marginLeft: '8px', fontSize: 'var(--text-xs)' }}> ${preflight.ok ? "passed" : "failed"} </span>`
                            ) : null} </label> <div class=${"preflight-panel"}> ${!draftExists ? (
                              html`<div class=${"muted"}>Create a draft session to run preflight.</div>`
                            ) : !preflight ? (
                              html`<div class=${"muted"}>Run preflight to validate pack scripts and prerequisites.</div>`
                            ) : (
                              html`<div class=${"preflight-list"}> <div class=${"preflight-row"}> <div class=${"row"}> <span class=${"status-dot"} style=${{ background: preflight.permission_report.ok ? "var(--status-done)" : "var(--status-blocked)" }} /> <span>Script permissions</span> </div> <span>${preflight.permission_report.ok ? "ok" : "fix required"}</span> </div> ${(preflight.permission_report.issues || []).map((issue) => (
                                  html`<div key=${issue.relative_path} class=${"field-hint"}>${issue.fix_command}</div>`
                                ))} ${(preflight.prerequisite_results?.results || []).map((result) => (
                                  html`<${preact.Fragment} key=${result.name}> <div class=${"preflight-row"}> <div class=${"row"}> <span class=${"status-dot"} style=${{ background: result.ok ? "var(--status-done)" : "var(--status-blocked)" }} /> <span>${result.name}</span> </div> <span>${result.ok ? "ok" : `failed (exit ${result.exit_code})`}</span> </div> ${!result.ok && (result.stderr || result.stdout) ? (
                                      html`<pre class=${"preflight-output"}>${(result.stderr || result.stdout).trim()}</pre>`
                                    ) : null} <//>`
                                ))} ${preflight.preflight_result ? (
                                  html`<${preact.Fragment}> <div class=${"preflight-row"}> <div class=${"row"}> <span class=${"status-dot"} style=${{ background: preflight.preflight_result.ok ? "var(--status-done)" : "var(--status-blocked)" }} /> <span>Pack preflight hook</span> </div> <span>${preflight.preflight_result.ok ? "ok" : `failed (exit ${preflight.preflight_result.exit_code})`}</span> </div> ${!preflight.preflight_result.ok && (preflight.preflight_result.stderr || preflight.preflight_result.stdout) ? (
                                      html`<pre class=${"preflight-output"}>${(preflight.preflight_result.stderr || preflight.preflight_result.stdout).trim()}</pre>`
                                    ) : null} <//>`
                                ) : null} </div>`
                            )} </div> </div> <div class=${"action-row"}> ${isIdle ? (
                            html`<button type=${"button"} class=${"action-button"} onClick=${onNewRun} disabled=${isBusy}> New Run </button>`
                          ) : !draftExists ? (
                            html`<button type=${"button"} class=${"action-button"} onClick=${onCreateDraft} disabled=${isBusy || !setupDraft.pack}> Create Session </button>`
                          ) : (
                            html`<button type=${"button"} class=${"action-button"} onClick=${onStartSession} disabled=${isBusy || !canStart}> Start Session </button>`
                          )} </div> </div> </section> </div>`
                );
              }

              function HealthSummaryBar({ tasks, workers }) {
                const [tick, setTick] = useState(0);

                const activeWorkers = (workers || []).filter(w => w.status === "active");
                useEffect(() => {
                  if (activeWorkers.length === 0) return;
                  const id = setInterval(() => setTick(t => t + 1), 1000);
                  return () => clearInterval(id);
                }, [activeWorkers.length]);

                const counts = { done: 0, active: 0, ready: 0, blocked: 0 };
                (tasks || []).forEach(t => {
                  if (counts[t.status] !== undefined) counts[t.status]++;
                });

                const maxElapsed = activeWorkers.reduce((m, w) => Math.max(m, w.elapsed || 0), 0) + tick;

                const doneTasks = (tasks || []).filter(t => t.completed_at).sort((a, b) => b.completed_at.localeCompare(a.completed_at));
                const lastCompletion = doneTasks.length ? doneTasks[0].completed_at.slice(11, 19) : null;

                const parts = [];
                if (counts.done) parts.push(`${counts.done} done`);
                if (counts.active) parts.push(`${counts.active} active (${formatElapsed(maxElapsed)})`);
                if (counts.ready) parts.push(`${counts.ready} ready`);
                if (counts.blocked) parts.push(`${counts.blocked} blocked`);
                if (lastCompletion) parts.push(`Last completion: ${lastCompletion}`);

                if (parts.length === 0) return null;

                return (
                  html`<div class=${"health-summary mono"} style=${{
                    fontSize: 'var(--text-xs)',
                    color: 'var(--text-secondary)',
                    padding: '4px 12px',
                    display: 'flex',
                    gap: '12px',
                    flexWrap: 'wrap',
                  }}> ${parts.join(" — ")} </div>`
                );
              }

              function TaskRowElapsed({ task }) {
                const [now, setNow] = useState(Date.now());
                useEffect(() => {
                  if (task.status !== "active" || !task.started_at) return;
                  const id = setInterval(() => setNow(Date.now()), 1000);
                  return () => clearInterval(id);
                }, [task.status, task.started_at]);

                if (!task.started_at) return html`<span class=${"mono muted"}>${formatElapsed(0)}</span>`;

                const seconds = task.status === "active"
                  ? Math.floor((now - new Date(task.started_at).getTime()) / 1000)
                  : (task.elapsed || 0);

                return html`<span class=${"mono muted"}>${formatElapsed(seconds)}</span>`;
              }

              function LastActivityIndicator({ worker }) {
                const [tick, setTick] = useState(0);
                const snapshotRef = useRef(worker.last_activity_ago || 0);

                useEffect(() => {
                  snapshotRef.current = worker.last_activity_ago || 0;
                  setTick(0);
                }, [worker.last_activity_ago]);

                useEffect(() => {
                  if (worker.status !== "active") return;
                  const id = setInterval(() => setTick(t => t + 1), 1000);
                  return () => clearInterval(id);
                }, [worker.status]);

                if (worker.status !== "active" || worker.last_activity_ago == null) return null;

                const ago = snapshotRef.current + tick;
                const limit = worker.task_idle_limit;
                const thirdLow  = (limit > 0) ? limit / 3       : 120;
                const thirdHigh = (limit > 0) ? (limit * 2) / 3  : 600;

                let color, style;
                if (ago < thirdLow) {
                  color = "var(--status-done)";
                  style = { fontSize: 'var(--text-xs)', color, opacity: 0.7 };
                } else if (ago < thirdHigh) {
                  color = "var(--status-review)";
                  style = { fontSize: 'var(--text-xs)', color, animation: 'pulse-idle-amber 3s ease-in-out infinite' };
                } else {
                  color = "var(--status-blocked)";
                  style = { fontSize: 'var(--text-xs)', color, animation: 'pulse-idle-red 1.5s ease-in-out infinite', fontWeight: 600 };
                }

                return (
                  html`<span class=${"mono"} style=${style}> ${`idle: ${formatElapsed(ago)}`} </span>`
                );
              }

              function ElapsedField({ task }) {
                const [now, setNow] = useState(Date.now());

                useEffect(() => {
                  if (task.status !== "active" || !task.started_at) return;
                  const id = setInterval(() => setNow(Date.now()), 1000);
                  return () => clearInterval(id);
                }, [task.status, task.started_at]);

                if (!task.started_at) return null;

                const label = task.status === "active" ? "Elapsed" : "Duration";
                const seconds = task.status === "active"
                  ? Math.floor((now - new Date(task.started_at).getTime()) / 1000)
                  : (task.elapsed || 0);

                return (
                  html`<div> <div class=${"field-label"}>${label}</div> <div class=${"metadata-value mono"}>${formatElapsed(seconds)}</div> </div>`
                );
              }

              function TaskDetailView({ task, currentSession, logLines, taskLogs, sessionStatus, runtimeState, searchValue, onSearchChange, onBack, onMoveTask, onRevealFile }) {
                const logPanelRef = useRef(null);
                const effectiveLogLines = useMemo(() => {
                  const baseLines = logLines || [];
                  if (!task) return baseLines;

                  const isAutoFix = sessionStatus === "auto_fixing";
                  const isVerifying = sessionStatus === "verifying";
                  const isTargetTask = runtimeState?.auto_fix_task_id === task.task_id;

                  if (!isTargetTask || (!isAutoFix && !isVerifying)) {
                    return baseLines;
                  }

                  const phaseKey = isAutoFix ? "__phase_auto_fix__" : "__phase_verification__";
                  const phaseLines = (taskLogs || {})[phaseKey] || [];
                  if (phaseLines.length === 0) return baseLines;

                  const separator = isAutoFix
                    ? "─── Auto-fix output ───"
                    : "─── Verification output ───";
                  return [...baseLines, { line: "", ts: null }, { line: separator, ts: null }, ...phaseLines];
                }, [logLines, task, sessionStatus, runtimeState, taskLogs]);
                const emptyLogMessage = useMemo(() => {
                  if (!task) {
                    return "Waiting for live log subscription...";
                  }
                  if (task.history_source === "summary") {
                    return "Task logs were not retained for this completed session.";
                  }
                  if (task.status === "active") {
                    return "Waiting for live log subscription...";
                  }
                  if (task.status === "done" || task.status === "blocked") {
                    return "No retained log found for this task.";
                  }
                  return "No log yet. Logs appear after the task starts.";
                }, [task]);

                useEffect(() => {
                  if (logPanelRef.current) {
                    logPanelRef.current.scrollTop = logPanelRef.current.scrollHeight;
                  }
                }, [effectiveLogLines.length]);

                return (
                  html`<div class=${"split-view"}> <aside class=${"detail-panel"}> <button type=${"button"} class=${"secondary-button"} onClick=${onBack}> ${icon("arrow-left", { width: 16, height: 16 })} Back to Monitor </button> ${task ? (
                        html`<div> <h1 class=${"mono"} style=${{ fontSize: "var(--text-xl)", marginBottom: "8px" }}>${task.task_id}</h1> <div class=${"secondary"}>${task.title}</div> <div style=${{ marginTop: "16px" }}> <span class=${"status-badge"} style=${statusBadgeStyle(task.status)}>${task.status}</span> ${task.full_test_after ? (
                              html`<span title=${"Full test after completion"} style=${{
                                fontSize: 'var(--text-xs)',
                                color: 'var(--status-active)',
                                fontWeight: 600,
                                padding: '0 4px',
                                background: 'rgba(245, 158, 11, 0.15)',
                                borderRadius: '3px',
                                marginLeft: '8px',
                              }}>FTA</span>`
                            ) : null} </div> <div class=${"metadata-grid"}> <div> <div class=${"field-label"}>Session</div> <div class=${"metadata-value mono"}>${currentSession?.name || "n/a"}</div> </div> <div> <div class=${"field-label"}>Worker Slot</div> <div class=${"metadata-value mono"}>${task.worker_slot ?? "n/a"}</div> </div> <div> <div class=${"field-label"}>Plan Path</div> <div class=${"metadata-value mono"}>${task.plan_path}</div> </div> <div> <div class=${"field-label"}>Created</div> <div class=${"metadata-value mono"}>${task.created_at || "n/a"}</div> </div> ${task.started_at ? (
                              html`<div> <div class=${"field-label"}>Started</div> <div class=${"metadata-value mono"} title=${task.started_at}>${task.started_at.slice(11, 19)}</div> </div>`
                            ) : null} <${ElapsedField} task=${task} /> ${task.completed_at ? (
                              html`<div> <div class=${"field-label"}>Completed</div> <div class=${"metadata-value mono"} title=${task.completed_at}>${task.completed_at.slice(11, 19)}</div> </div>`
                            ) : null} <div> <div class=${"field-label"}>Constraints</div> <div class=${"constraint-list"}> <div class=${"metadata-value mono"}>${`DEPENDS_ON: ${(task.depends_on || []).join(", ") || "none"}`}</div> <div class=${"metadata-value mono"}>${`ANTI_AFFINITY: ${(task.anti_affinity || []).join(", ") || "none"}`}</div> <div class=${"metadata-value mono"}>${`FULL_TEST_AFTER: ${task.full_test_after ? "yes" : "no"}`}</div> </div> </div> </div> ${(() => {
                            const actions = TASK_TRANSITIONS[task.status];
                            if (!actions || actions.length === 0) return null;
                            return (
                              html`<div style=${{ marginTop: '16px', display: 'flex', gap: '8px', flexWrap: 'wrap' }}> ${actions.map(({ target, label, icon: iconName }) => (
                                  html`<button key=${target} type=${"button"} class=${"secondary-button"} onClick=${async (e) => {
                                      e.stopPropagation();
                                      await onMoveTask(task.task_id, target);
                                      if (target === "intake") {
                                        onBack();
                                      }
                                    }}> ${icon(iconName, { width: 14, height: 14 })} ${label} </button>`
                                ))} <button type=${"button"} class=${"secondary-button"} onClick=${() => onRevealFile(task.plan_path)} title=${"Open plan file in Finder/editor"}> ${icon("file-text", { width: 14, height: 14 })} Reveal File </button> </div>`
                            );
                          })()} </div>`
                      ) : (
                        html`<div class=${"empty-state"}>Select a task from the monitor.</div>`
                      )} </aside> <section class=${"log-panel"} ref=${logPanelRef}> <div style=${{ position: "sticky", top: 0, background: "rgba(10, 12, 16, 0.96)", paddingBottom: "12px" }}> <input class=${"search-input"} placeholder=${"Search log output"} value=${searchValue} onInput=${(event) => onSearchChange(event.target.value)} /> </div> ${(effectiveLogLines.length ? effectiveLogLines : [{ line: emptyLogMessage, ts: null }]).map((entry, index) => (
                        html`<div key=${`${index}-${entry.line}`} class=${`log-line ${entry.line.startsWith("───") ? "separator" : isProgressLine(entry.line) ? "progress" : isProblemLine(entry.line) ? "error" : ""}`}> ${entry.ts ? html`<span class=${"muted"} style=${{ marginRight: '8px' }}>${entry.ts.slice(11, 19)}</span>` : null} ${entry.line} </div>`
                      ))} </section> </div>`
                );
              }

              function DagCanvas({ nodes, edges, setNodes, setEdges, onOpenTask }) {
                const root = useRef(null);
                const drag = useRef(null);
                const touches = useRef(new Map());
                const pinch = useRef(null);
                const panTimer = useRef(null);
                const spaceDown = useRef(false);
                const suppressClick = useRef(false);
                const [viewport, setViewport] = useState({ x: 0, y: 0, zoom: 1 });
                const [selected, setSelected] = useState([]);
                const [selectedEdges, setSelectedEdges] = useState([]);
                const [selectionBox, setSelectionBox] = useState(null);
                const [connection, setConnection] = useState(null);
                const [interactive, setInteractive] = useState(true);
                const [size, setSize] = useState({ width: 1, height: 1 });
                const [dimensions, setDimensions] = useState({});
                const initialFit = useRef(false);
                const clamp = (zoom) => Math.max(0.5, Math.min(2, zoom));
                const nodeSize = (node) => dimensions[node.id] || { width: Number(node.style?.width) || 180, height: Number(node.style?.height) || 80 };
                const bounds = () => {
                  const items = nodes.filter((n) => !n.id.endsWith('-label'));
                  if (!items.length) return { x: 0, y: 0, width: 1, height: 1 };
                  const x = Math.min(...items.map((n) => n.position.x));
                  const y = Math.min(...items.map((n) => n.position.y));
                  const right = Math.max(...items.map((n) => n.position.x + nodeSize(n).width));
                  const bottom = Math.max(...items.map((n) => n.position.y + nodeSize(n).height));
                  return { x, y, width: Math.max(1, right - x), height: Math.max(1, bottom - y) };
                };
                const fit = () => {
                  const r = root.current?.getBoundingClientRect();
                  if (!r || !r.width || !r.height) return;
                  const b = bounds();
                  const zoom = clamp(Math.min(r.width / (b.width * 1.2), r.height / (b.height * 1.2)));
                  setViewport({ x: (r.width - b.width * zoom) / 2 - b.x * zoom, y: (r.height - b.height * zoom) / 2 - b.y * zoom, zoom });
                };
                const zoomAt = (factor, x, y) => setViewport((v) => {
                  const zoom = clamp(v.zoom * factor);
                  return { x: x - (x - v.x) * zoom / v.zoom, y: y - (y - v.y) * zoom / v.zoom, zoom };
                });
                useEffect(() => {
                  const el = root.current;
                  const resize = () => setSize({ width: el.clientWidth, height: el.clientHeight });
                  const observer = new ResizeObserver(resize);
                  observer.observe(el); resize();
                  const nodeObserver = new ResizeObserver((entries) => {
                    setDimensions((current) => {
                      const next = { ...current }; let changed = false;
                      for (const entry of entries) {
                        const id = entry.target.dataset.id, width = entry.target.offsetWidth, height = entry.target.offsetHeight;
                        if (current[id]?.width !== width || current[id]?.height !== height) { next[id] = { width, height }; changed = true; }
                      }
                      return changed ? next : current;
                    });
                  });
                  el.querySelectorAll('.dag-node').forEach((node) => nodeObserver.observe(node));
                  const wheel = (e) => { e.preventDefault(); const r = el.getBoundingClientRect(); zoomAt(Math.pow(2, -e.deltaY * 0.002), e.clientX - r.left, e.clientY - r.top); };
                  const keyDown = (e) => { if (e.code === 'Space' && !['INPUT', 'TEXTAREA', 'SELECT'].includes(document.activeElement?.tagName)) spaceDown.current = true; };
                  const keyUp = (e) => { if (e.code === 'Space') spaceDown.current = false; };
                  const blur = () => { spaceDown.current = false; };
                  el.addEventListener('wheel', wheel, { passive: false });
                  window.addEventListener('keydown', keyDown); window.addEventListener('keyup', keyUp); window.addEventListener('blur', blur);
                  return () => { observer.disconnect(); nodeObserver.disconnect(); el.removeEventListener('wheel', wheel); window.removeEventListener('keydown', keyDown); window.removeEventListener('keyup', keyUp); window.removeEventListener('blur', blur); clearInterval(panTimer.current); };
                }, []);
                useEffect(() => {
                  if (!initialFit.current && nodes.every((node) => dimensions[node.id])) { initialFit.current = true; fit(); }
                }, [dimensions]);
                const onKey = (e) => {
                  if (e.key === 'Escape' && connection) { setConnection(null); return; }
                  if (e.key !== 'Backspace' || !interactive || (!selected.length && !selectedEdges.length)) return;
                  const tag = document.activeElement?.tagName;
                  if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;
                  e.preventDefault();
                  setNodes((current) => current.filter((n) => !selected.includes(n.id)));
                  setEdges((current) => current.filter((edge) => !selectedEdges.includes(edge.id) && !selected.includes(edge.source) && !selected.includes(edge.target)));
                  setSelected([]); setSelectedEdges([]);
                };
                const start = (e, node) => {
                  if (e.button !== 0 && e.button !== 1) return;
                  if (spaceDown.current) node = null;
                  if (connection?.clickMode) setConnection(null);
                  if (node && (node.draggable === false || !interactive)) node = null;
                  e.stopPropagation(); e.currentTarget.setPointerCapture(e.pointerId);
                  if (node && interactive && !e.metaKey && !e.ctrlKey && !selected.includes(node.id)) { setSelected([node.id]); setSelectedEdges([]); }
                  if (!node && !e.shiftKey) { setSelected([]); setSelectedEdges([]); }
                  if (!node && e.shiftKey && interactive) {
                    const r = root.current.getBoundingClientRect();
                    drag.current = { selecting: true, startX: e.clientX - r.left, startY: e.clientY - r.top, x: e.clientX - r.left, y: e.clientY - r.top };
                    setSelectionBox({ x: e.clientX - r.left, y: e.clientY - r.top, width: 0, height: 0 });
                    clearInterval(panTimer.current);
                    panTimer.current = setInterval(() => {
                      const d = drag.current;
                      if (!d?.selecting || !d.pan || (!d.pan.x && !d.pan.y)) return;
                      const { x, y } = d.pan;
                      setViewport((v) => ({ ...v, x: v.x + x, y: v.y + y }));
                      d.startX += x; d.startY += y;
                      setSelectionBox({ x: Math.min(d.startX, d.x), y: Math.min(d.startY, d.y), width: Math.abs(d.x - d.startX), height: Math.abs(d.y - d.startY) });
                    }, 16);
                    return;
                  }
                  if (e.pointerType === 'touch') {
                    touches.current.set(e.pointerId, { x: e.clientX, y: e.clientY });
                    if (touches.current.size === 2) {
                      const [a, b] = [...touches.current.values()];
                      const r = root.current.getBoundingClientRect();
                      pinch.current = { distance: Math.hypot(a.x - b.x, a.y - b.y) || 1, x: (a.x + b.x) / 2 - r.left, y: (a.y + b.y) / 2 - r.top, viewport };
                      drag.current = null;
                      return;
                    }
                  }
                  drag.current = { x: e.clientX, y: e.clientY, node, moved: false };
                  if (node) {
                    clearInterval(panTimer.current);
                    panTimer.current = setInterval(() => {
                      const d = drag.current;
                      if (!d?.node || !d.pan || (!d.pan.x && !d.pan.y)) return;
                      const { x, y } = d.pan;
                      setViewport((v) => ({ ...v, x: v.x + x, y: v.y + y }));
                      setNodes((current) => current.map((n) => (n.id === d.node.id || (selected.includes(d.node.id) && selected.includes(n.id))) ? { ...n, position: { x: n.position.x - x / viewport.zoom, y: n.position.y - y / viewport.zoom } } : n));
                    }, 16);
                  }
                };
                const move = (e) => {
                  if (drag.current?.connecting || connection?.clickMode) {
                    const r = root.current.getBoundingClientRect();
                    const x = (e.clientX - r.left - viewport.x) / viewport.zoom, y = (e.clientY - r.top - viewport.y) / viewport.zoom;
                    if (drag.current?.connecting && Math.hypot(e.clientX - drag.current.x, e.clientY - drag.current.y) > 3) drag.current.moved = true;
                    setConnection((current) => current ? { ...current, x, y } : current);
                    return;
                  }
                  if (e.pointerType === 'touch' && touches.current.has(e.pointerId)) {
                    touches.current.set(e.pointerId, { x: e.clientX, y: e.clientY });
                    if (pinch.current && touches.current.size === 2) {
                      const [a, b] = [...touches.current.values()], p = pinch.current;
                      const r = root.current.getBoundingClientRect(), x = (a.x + b.x) / 2 - r.left, y = (a.y + b.y) / 2 - r.top;
                      const zoom = clamp(p.viewport.zoom * Math.hypot(a.x - b.x, a.y - b.y) / p.distance);
                      setViewport({ x: x - (p.x - p.viewport.x) * zoom / p.viewport.zoom, y: y - (p.y - p.viewport.y) * zoom / p.viewport.zoom, zoom });
                      return;
                    }
                  }
                  const d = drag.current; if (!d) return;
                  if (d.selecting) {
                    const r = root.current.getBoundingClientRect(), x = e.clientX - r.left, y = e.clientY - r.top;
                    d.x = x; d.y = y;
                    d.pan = { x: x < 20 ? 15 : x > r.width - 20 ? -15 : 0, y: y < 20 ? 15 : y > r.height - 20 ? -15 : 0 };
                    setSelectionBox({ x: Math.min(d.startX, x), y: Math.min(d.startY, y), width: Math.abs(x - d.startX), height: Math.abs(y - d.startY) });
                    return;
                  }
                  const dx = e.clientX - d.x, dy = e.clientY - d.y;
                  if (Math.abs(dx) + Math.abs(dy) > 0) d.moved = true;
                  d.x = e.clientX; d.y = e.clientY;
                  if (d.node) {
                    const r = root.current.getBoundingClientRect();
                    d.pan = { x: e.clientX < r.left + 20 ? 15 : e.clientX > r.right - 20 ? -15 : 0, y: e.clientY < r.top + 20 ? 15 : e.clientY > r.bottom - 20 ? -15 : 0 };
                  }
                  if (d.node) setNodes((current) => current.map((n) => (n.id === d.node.id || (selected.includes(d.node.id) && selected.includes(n.id))) ? { ...n, position: { x: n.position.x + dx / viewport.zoom, y: n.position.y + dy / viewport.zoom } } : n));
                  else setViewport((v) => ({ ...v, x: v.x + dx, y: v.y + dy }));
                };
                const end = (e) => {
                  if (drag.current?.connecting) {
                    if (drag.current.moved || drag.current.completing) setConnection(null);
                    else setConnection((current) => current ? { ...current, clickMode: true } : current);
                    drag.current = null;
                    return;
                  }
                  if (e.pointerType === 'touch') touches.current.delete(e.pointerId);
                  if (drag.current?.selecting) {
                    const r = root.current.getBoundingClientRect(), d = drag.current, x = e.clientX - r.left, y = e.clientY - r.top;
                    const left = Math.min(d.startX, x), top = Math.min(d.startY, y), right = Math.max(d.startX, x), bottom = Math.max(d.startY, y);
                    setSelected(nodes.filter((n) => n.selectable !== false && n.position.x * viewport.zoom + viewport.x >= left && n.position.y * viewport.zoom + viewport.y >= top && (n.position.x + nodeSize(n).width) * viewport.zoom + viewport.x <= right && (n.position.y + nodeSize(n).height) * viewport.zoom + viewport.y <= bottom).map((n) => n.id));
                    setSelectionBox(null); setSelectedEdges([]); suppressClick.current = true; root.current.focus();
                  }
                  if (pinch.current || drag.current?.moved) suppressClick.current = true;
                  clearInterval(panTimer.current); panTimer.current = null;
                  pinch.current = null; drag.current = null;
                };
                const byId = new Map(nodes.map((n) => [n.id, n]));
                const startConnection = (e, node, source) => {
                  if (!interactive || e.button !== 0 || spaceDown.current) return;
                  e.stopPropagation(); e.currentTarget.setPointerCapture(e.pointerId);
                  root.current.focus();
                  if (connection?.clickMode) { drag.current = { connecting: true, completing: true, x: e.clientX, y: e.clientY }; return; }
                  const measured = nodeSize(node);
                  const x = node.position.x + measured.width / 2, y = node.position.y + (source ? measured.height : 0);
                  drag.current = { connecting: true, x: e.clientX, y: e.clientY, moved: false };
                  setConnection({ startX: x, startY: y, x, y, source });
                };
                const b = bounds();
                const viewX = -viewport.x / viewport.zoom, viewY = -viewport.y / viewport.zoom;
                const viewWidth = size.width / viewport.zoom, viewHeight = size.height / viewport.zoom;
                const minX = Math.min(b.x, viewX), minY = Math.min(b.y, viewY);
                const mapWidth = Math.max(b.x + b.width, viewX + viewWidth) - minX;
                const mapHeight = Math.max(b.y + b.height, viewY + viewHeight) - minY;
                const mapScale = Math.min(180 / Math.max(1, mapWidth), 130 / Math.max(1, mapHeight));
                const mapX = (200 - mapWidth * mapScale) / 2 - minX * mapScale, mapY = (150 - mapHeight * mapScale) / 2 - minY * mapScale;
                return html`<div class="dag-canvas-root" tabindex="-1" ref=${root} onKeyDown=${onKey} onPointerDown=${(e) => start(e, null)} onPointerMove=${move} onPointerUp=${end} onPointerCancel=${end} onDblClick=${(e) => { const r = root.current.getBoundingClientRect(); zoomAt(2, e.clientX - r.left, e.clientY - r.top); }}>
                  <div class="dag-viewport" style=${{ transform: `translate(${viewport.x}px, ${viewport.y}px) scale(${viewport.zoom})` }}>
                    <svg class="dag-edges" width="1" height="1"><defs><marker id="dag-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" fill="var(--text-muted)" /></marker></defs>
                      ${connection ? html`<path class="dag-connection-preview" d=${`M ${connection.startX} ${connection.startY} C ${connection.startX} ${connection.startY + (connection.source ? 25 : -25)}, ${connection.x} ${connection.y + (connection.source ? -25 : 25)}, ${connection.x} ${connection.y}`} fill="none" stroke="#b1b1b7" stroke-width="1" />` : null}
                      ${edges.map((edge) => { const a = byId.get(edge.source), z = byId.get(edge.target); if (!a || !z) return null; const x1 = a.position.x + nodeSize(a).width / 2, y1 = a.position.y + nodeSize(a).height, x2 = z.position.x + nodeSize(z).width / 2, y2 = z.position.y, bend = Math.max(25, Math.sqrt(Math.abs(y2 - y1)) * 6.25); const path = `M ${x1} ${y1} C ${x1} ${y1 + bend}, ${x2} ${y2 - bend}, ${x2} ${y2}`; return html`<g tabindex="0" data-selected=${selectedEdges.includes(edge.id) ? "true" : "false"} onPointerDown=${(e) => e.stopPropagation()} onClick=${(e) => { e.stopPropagation(); e.currentTarget.focus(); if (interactive) { const multi = e.metaKey || e.ctrlKey; if (!multi) setSelected([]); setSelectedEdges((current) => multi ? (current.includes(edge.id) ? current.filter((id) => id !== edge.id) : [...current, edge.id]) : [edge.id]); } }} onKeyDown=${(e) => { if (interactive && e.key === "Enter") { setSelected([]); setSelectedEdges([edge.id]); } }}><path d=${path} fill="none" stroke="transparent" stroke-width="20" style=${{ pointerEvents: "stroke" }} /><path class=${`dag-edge${edge.animated ? ' animated' : ''}`} d=${path} fill="none" stroke=${edge.style.stroke} stroke-width=${edge.style.strokeWidth} stroke-dasharray=${edge.style.strokeDasharray} marker-end=${edge.markerEnd ? 'url(#dag-arrow)' : undefined} /></g>`; })}
                    </svg>
                    ${nodes.map((node) => html`<div key=${node.id} data-id=${node.id} class=${`dag-node${node.id.startsWith('group-') ? '' : ' dag-task-node'}${selected.includes(node.id) ? ' selected' : ''}`} tabindex=${node.selectable === false ? undefined : 0} style=${{ ...node.style, left: node.position.x, top: node.position.y }} onPointerDown=${(e) => start(e, node)} onClick=${(e) => { e.stopPropagation(); if (suppressClick.current) { suppressClick.current = false; return; } if (interactive && node.selectable !== false) { setSelected((current) => e.metaKey || e.ctrlKey ? (current.includes(node.id) ? current.filter((id) => id !== node.id) : [...current, node.id]) : [node.id]); if (!e.metaKey && !e.ctrlKey) setSelectedEdges([]); } }} onKeyDown=${(e) => { const delta = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] }[e.key]; if (interactive && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); setSelected([node.id]); setSelectedEdges([]); } else if (delta && interactive && node.draggable !== false) { e.preventDefault(); const step = e.shiftKey ? 4 : 1; setNodes((current) => current.map((n) => (n.id === node.id || (selected.includes(node.id) && selected.includes(n.id))) ? { ...n, position: { x: n.position.x + delta[0] * step, y: n.position.y + delta[1] * step } } : n)); } }} onDblClick=${(e) => { e.stopPropagation(); if (!node.id.startsWith('group-') && !suppressClick.current) onOpenTask(node.id); }}>${node.type === "group" ? null : node.data.label}${node.id.startsWith("group-") ? null : html`<span class="dag-handle dag-target-handle" onPointerDown=${(e) => startConnection(e, node, false)} onClick=${(e) => e.stopPropagation()} /><span class="dag-handle dag-source-handle" onPointerDown=${(e) => startConnection(e, node, true)} onClick=${(e) => e.stopPropagation()} />`}</div>`)}
                  </div>
                  ${selectionBox ? html`<div style=${{ position: 'absolute', left: selectionBox.x, top: selectionBox.y, width: selectionBox.width, height: selectionBox.height, background: 'rgba(0, 89, 220, .08)', border: '1px dotted #0059dc', pointerEvents: 'none' }} />` : null}
                  <div class="dag-controls" onPointerDown=${(e) => e.stopPropagation()}><button class="dag-zoom-in" aria-label="zoom in" onClick=${() => zoomAt(1.2, size.width / 2, size.height / 2)}>+</button><button class="dag-zoom-out" aria-label="zoom out" onClick=${() => zoomAt(1 / 1.2, size.width / 2, size.height / 2)}>−</button><button class="dag-fit-view" aria-label="fit view" onClick=${fit}>⛶</button><button class="dag-toggle-interactivity" aria-label="toggle interactivity" aria-pressed=${!interactive} onClick=${() => setInteractive((value) => !value)}><svg viewBox="0 0 24 24"><path d=${interactive ? 'M18 8h-1V6a5 5 0 0 0-9.9-1H9.2A3 3 0 0 1 15 6v2H6a2 2 0 0 0-2 2v10a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V10a2 2 0 0 0-2-2z' : 'M18 8h-1V6A5 5 0 0 0 7 6v2H6a2 2 0 0 0-2 2v10a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V10a2 2 0 0 0-2-2zM9 6a3 3 0 0 1 6 0v2H9z'} /></svg></button></div>
                  <svg class="dag-minimap" viewBox="0 0 200 150" onPointerDown=${(e) => e.stopPropagation()}><rect width="200" height="150" fill="#f0f0f0" /><rect class="dag-minimap-viewport" x=${mapX - viewport.x / viewport.zoom * mapScale} y=${mapY - viewport.y / viewport.zoom * mapScale} width=${size.width / viewport.zoom * mapScale} height=${size.height / viewport.zoom * mapScale} fill="white" stroke="#ddd" />${nodes.filter((n) => !n.id.startsWith('group-')).map((n) => html`<rect x=${mapX + n.position.x * mapScale} y=${mapY + n.position.y * mapScale} width=${nodeSize(n).width * mapScale} height=${nodeSize(n).height * mapScale} fill="#161922" />`)}</svg>
                </div>`;
              }

              function DagView({ dag, liveTasks, onBack, onOpenTask }) {
                // The DAG payload is fetched once; overlay the live task list
                // (kept current over WebSocket) so labels and colors stay fresh.
                const tasks = useMemo(() => {
                  const liveById = new Map((liveTasks || []).map((task) => [task.task_id, task]));
                  return (dag?.tasks || []).map((task) => {
                    const live = liveById.get(task.task_id);
                    return live
                      ? { ...task, title: live.title ?? task.title, status: live.status ?? task.status }
                      : task;
                  });
                }, [dag, liveTasks]);
                const groups = dag?.groups || [];

                // Topological layout: compute depth per node from dependencies
                const nodeWidth = 180;
                const nodeHeight = 80;
                const colGap = 260;
                const rowGap = 120;
                const padding = 40;

                const depthMap = useMemo(() => {
                  const depths = {};
                  const taskIds = new Set(tasks.map((t) => t.task_id));
                  function computeDepth(taskId, visited) {
                    if (depths[taskId] !== undefined) return depths[taskId];
                    if (visited.has(taskId)) return 0;
                    visited.add(taskId);
                    const task = tasks.find((t) => t.task_id === taskId);
                    if (!task) return 0;
                    const parentDepths = (task.depends_on || [])
                      .filter((dep) => taskIds.has(dep))
                      .map((dep) => computeDepth(dep, visited));
                    depths[taskId] = parentDepths.length > 0 ? Math.max(...parentDepths) + 1 : 0;
                    return depths[taskId];
                  }
                  tasks.forEach((t) => computeDepth(t.task_id, new Set()));
                  return depths;
                }, [tasks]);

                // Group tasks by depth column, then assign y positions
                const positions = useMemo(() => {
                  const columns = {};
                  tasks.forEach((task) => {
                    const col = depthMap[task.task_id] || 0;
                    if (!columns[col]) columns[col] = [];
                    columns[col].push(task.task_id);
                  });
                  const pos = {};
                  Object.entries(columns).forEach(([col, ids]) => {
                    const c = parseInt(col, 10);
                    ids.forEach((id, row) => {
                      pos[id] = { x: padding + c * colGap, y: padding + row * rowGap };
                    });
                  });
                  return pos;
                }, [tasks, depthMap]);

                // Anti-affinity group background nodes
                const groupColors = [
                  "rgba(167, 139, 250, 0.08)", // purple
                  "rgba(59, 130, 246, 0.08)",   // blue
                  "rgba(245, 158, 11, 0.08)",   // amber
                  "rgba(52, 211, 153, 0.08)",   // green
                  "rgba(239, 68, 68, 0.08)",    // red
                ];
                const groupBorderColors = [
                  "rgba(167, 139, 250, 0.25)",
                  "rgba(59, 130, 246, 0.25)",
                  "rgba(245, 158, 11, 0.25)",
                  "rgba(52, 211, 153, 0.25)",
                  "rgba(239, 68, 68, 0.25)",
                ];

                const groupNodes = useMemo(() => {
                  return groups.map((group, gi) => {
                    const memberPositions = (group.members || [])
                      .filter((m) => positions[m])
                      .map((m) => positions[m]);
                    if (memberPositions.length === 0) return null;
                    const groupPad = 24;
                    const minX = Math.min(...memberPositions.map((p) => p.x)) - groupPad;
                    const minY = Math.min(...memberPositions.map((p) => p.y)) - groupPad - 28;
                    const maxX = Math.max(...memberPositions.map((p) => p.x)) + nodeWidth + groupPad;
                    const maxY = Math.max(...memberPositions.map((p) => p.y)) + nodeHeight + groupPad;
                    return {
                      id: `group-${group.name}`,
                      type: "group",
                      position: { x: minX, y: minY },
                      data: { label: group.name },
                      style: {
                        width: maxX - minX,
                        height: maxY - minY,
                        background: groupColors[gi % groupColors.length],
                        border: `1px dashed ${groupBorderColors[gi % groupBorderColors.length]}`,
                        borderRadius: "var(--radius-xl)",
                        padding: 0,
                        zIndex: -1,
                      },
                      selectable: false,
                      draggable: false,
                    };
                  }).filter(Boolean);
                }, [groups, positions]);

                // Group label nodes (React Flow group type doesn't render labels)
                const groupLabelNodes = useMemo(() => {
                  return groupNodes.map((gn) => ({
                    id: `${gn.id}-label`,
                    position: { x: gn.position.x + 12, y: gn.position.y + 6 },
                    data: {
                      label: (
                        html`<div style=${{
                          fontSize: "var(--text-xs)",
                          color: "var(--text-muted)",
                          fontFamily: "var(--font-mono)",
                          letterSpacing: "0.05em",
                          textTransform: "uppercase",
                          pointerEvents: "none",
                        }}>${gn.data.label}</div>`
                      )
                    },
                    style: {
                      background: "transparent",
                      border: "none",
                      padding: 0,
                      width: "auto",
                      boxShadow: "none",
                    },
                    selectable: false,
                    draggable: false,
                  }));
                }, [groupNodes]);

                const graphNodes = tasks.map((task) => ({
                  id: task.task_id,
                  position: positions[task.task_id] || { x: 0, y: 0 },
                  data: {
                    label: (
                      html`<div> <div class=${"mono"}>${task.task_id}</div> <div class=${"secondary"}>${task.title || "Task"}</div> <div class=${"status-badge"} style=${statusBadgeStyle(task.status || "ready")}> ${task.status || "ready"} </div> </div>`
                    )
                  },
                  style: {
                    width: nodeWidth,
                    minHeight: 60,
                    background: "var(--bg-surface)",
                    border: `2px solid ${STATUS_COLORS[task.status || "ready"] || "var(--status-ready)"}`,
                    borderRadius: "var(--radius-lg)",
                    color: "var(--text-primary)"
                  }
                }));
                const dependsEdges = tasks.flatMap((task) => (
                  (task.depends_on || []).map((dependency) => ({
                    id: `${dependency}-${task.task_id}`,
                    source: dependency,
                    target: task.task_id,
                    animated: true,
                    markerEnd: { type: "arrowclosed" },
                    style: { stroke: "var(--text-muted)", strokeWidth: 2 }
                  }))
                ));
                const antiAffinityEdges = tasks.flatMap((task) => (
                  (task.anti_affinity || []).map((peer) => ({
                    id: `${task.task_id}-${peer}-anti-affinity`,
                    source: task.task_id,
                    target: peer,
                    animated: false,
                    style: { stroke: "var(--status-staged)", strokeWidth: 1, strokeDasharray: "6 4" }
                  }))
                ));
                const allNodes = [...groupNodes, ...groupLabelNodes, ...graphNodes];
                const allEdges = [...dependsEdges, ...antiAffinityEdges];
                const [flowNodes, setFlowNodes] = useState(allNodes);
                const [flowEdges, setFlowEdges] = useState(allEdges);
                // flowNodes owns positions and selection after the first render;
                // refresh only each task node's label and border on status changes.
                const taskStateKey = JSON.stringify(tasks.map((task) => [task.task_id, task.title || "", task.status || ""]));
                useEffect(() => {
                  const graphNodesById = new Map(graphNodes.map((node) => [node.id, node]));
                  setFlowNodes((currentNodes) => currentNodes.map((node) => {
                    const next = graphNodesById.get(node.id);
                    return next ? { ...node, data: next.data, style: next.style } : node;
                  }));
                }, [taskStateKey]);
                return (
                  html`<div class=${"dag-shell"}> <div class=${"page"}> <button type=${"button"} class=${"secondary-button"} onClick=${onBack}> ${icon("arrow-left", { width: 16, height: 16 })} Back to Monitor </button> </div> ${dag ? (
                      html`<div class=${"dag-canvas"}><${DagCanvas} nodes=${flowNodes} edges=${flowEdges} setNodes=${setFlowNodes} setEdges=${setFlowEdges} onOpenTask=${onOpenTask} /></div>`
                    ) : (
                      html`<div class=${"empty-state"}>DAG data will appear here once a session has a graph.</div>`
                    )} </div>`
                );
              }

              function HistoryView({ sessions, settings, selectedSession, selectedTasks, onOpenSession, onOpenSettings, onPurgeSession, onPurgeAll }) {
                const completed = sessions.filter((session) => session.status === "completed" || session.status === "aborted");
                return (
                  html`<main class=${"page"}> <div class=${"row"} style=${{ justifyContent: "space-between", marginBottom: "24px" }}> <h1 style=${{ margin: 0, fontFamily: "var(--font-display)", fontSize: "var(--text-xl)" }}>Session History</h1> <div class=${"action-row"}> <button type=${"button"} class=${"secondary-button"} onClick=${onOpenSettings}> Retention </button> <button type=${"button"} class=${"danger-button"} onClick=${onPurgeAll}> Purge All </button> </div> </div> <section class=${"history-list"}> ${completed.length === 0 ? (
                        html`<div class=${"empty-state"}> ${icon("inbox", { width: 32, height: 32 })} <div>No sessions yet</div> </div>`
                      ) : completed.map((session) => (
                        html`<article key=${session.id} class=${"session-card"}> <div class=${"session-card-header"}> <div onClick=${() => onOpenSession(session)} style=${{ cursor: "pointer", flex: 1 }}> <div style=${{ fontFamily: "var(--font-display)", fontWeight: 600 }}>${session.name}</div> <div class=${"secondary mono"}>${session.pack}</div> <div class=${"secondary mono"} style=${{ marginTop: "12px" }}> ${`${session.created_at} -> ${session.completed_at || "in progress"}`} </div> </div> <div class=${"stack"} style=${{ justifyItems: "end" }}> <span class=${"status-badge"} style=${statusBadgeStyle(session.status)}>${session.status}</span> <button type=${"button"} class=${"icon-button"} onClick=${() => onPurgeSession(session.id)} aria-label=${`Purge ${session.name}`}> ${icon("trash-2", { width: 16, height: 16 })} </button> </div> </div> </article>`
                      ))} </section> ${selectedSession ? (
                      html`<section class=${"setup-card"} style=${{ marginTop: "24px" }}> <div class=${"row"} style=${{ justifyContent: "space-between", alignItems: "flex-start" }}> <div> <h2 style=${{ margin: 0, fontFamily: "var(--font-display)", fontSize: "var(--text-lg)" }}>${selectedSession.name}</h2> <div class=${"secondary mono"}>${selectedSession.pack}</div> </div> <span class=${"status-badge"} style=${statusBadgeStyle(selectedSession.status)}>${selectedSession.status}</span> </div> <div class=${"secondary mono"} style=${{ marginTop: "12px" }}> ${`${selectedSession.started_at || selectedSession.created_at} -> ${selectedSession.completed_at || "in progress"}`} </div> ${selectedSession?.release_notes?.content ? (
                          html`<section class=${"section-card"} style=${{ marginTop: "20px", padding: "16px" }}> <div style=${{ fontFamily: "var(--font-display)", fontSize: "var(--text-md)", fontWeight: 700, marginBottom: "12px" }}> Release Notes </div> <pre class=${"log-panel"} style=${{ margin: 0, whiteSpace: "pre-wrap" }}> ${selectedSession.release_notes.content} </pre> </section>`
                        ) : null} <div class=${"stack"} style=${{ marginTop: "20px", gap: "12px" }}> ${(selectedTasks || []).map((task) => (
                            html`<div key=${task.task_id} class=${"session-card"}> <div class=${"session-card-header"}> <div> <div style=${{ fontFamily: "var(--font-display)", fontWeight: 600 }}>${task.title}</div> <div class=${"secondary mono"}>${task.task_id}</div> </div> <span class=${"status-badge"} style=${statusBadgeStyle(task.status)}>${task.status}</span> </div> </div>`
                          ))} </div> </section>`
                    ) : null} <div class=${"retention-line"}> ${`Auto-purge: ${settings?.retention_days ? `sessions older than ${settings.retention_days} days` : "disabled"}`} </div> </main>`
                );
              }

              function SettingsView({ settingsDraft, setSettingsDraft, packs, onSave }) {
                return (
                  html`<main class=${"page"}> <section class=${"setup-card"} style=${{ margin: "0 auto" }}> <h1 style=${{ fontFamily: "var(--font-display)", fontSize: "var(--text-xl)", marginTop: 0 }}>Settings</h1> <div class=${"settings-grid"}> <div> <label class=${"field-label"}>Session Retention (days)</label> <input class=${"text-input"} type=${"number"} value=${settingsDraft.retention_days} onInput=${(event) => setSettingsDraft((draft) => ({ ...draft, retention_days: Number(event.target.value) }))} /> </div> <div class=${"row"}> <div style=${{ flex: 1 }}> <label class=${"field-label"}>Default Planner Count</label> <input class=${"text-input"} type=${"number"} value=${settingsDraft.default_planners} onInput=${(event) => setSettingsDraft((draft) => ({ ...draft, default_planners: Number(event.target.value) }))} /> </div> <div style=${{ flex: 1 }}> <label class=${"field-label"}>Default Worker Count</label> <input class=${"text-input"} type=${"number"} value=${settingsDraft.default_workers} onInput=${(event) => setSettingsDraft((draft) => ({ ...draft, default_workers: Number(event.target.value) }))} /> </div> </div> <div> <label class=${"field-label"}>Default Pack</label> <select class=${"select-input"} value=${settingsDraft.default_pack} onInput=${(event) => setSettingsDraft((draft) => ({ ...draft, default_pack: event.target.value }))}> ${packs.map((pack) => html`<option key=${pack.name} value=${pack.name}>${pack.name}</option>`)} </select> </div> <div> <label class=${"field-label"}>Terminal Application</label> <input class=${"text-input"} list=${"terminal-options"} value=${settingsDraft.terminal_app || ""} onInput=${(event) => setSettingsDraft((draft) => ({ ...draft, terminal_app: event.target.value }))} placeholder=${"e.g. iTerm, Terminal, Kitty"} /> <datalist id=${"terminal-options"}> <option value=${"iTerm"} /> <option value=${"Terminal"} /> <option value=${"Wezterm"} /> <option value=${"Kitty"} /> <option value=${"Alacritty"} /> </datalist> </div> <button type=${"button"} class=${"action-button"} onClick=${onSave}>Save Settings</button> </div> </section> </main>`
                );
              }

              preact.render(html`<${App} />`, document.getElementById("switchyard-app"));
            </script>
          </body>
        </html>
        """
    )
    return (
        template
        .replace("<!-- frontend-vendor -->", FRONTEND_VENDOR_HTML)
        .replace("__DESIGN_TOKENS_BLOCK__", DESIGN_TOKENS_BLOCK)
        .replace("__BOOTSTRAP_JSON__", _escape_json_for_inline_html(bootstrap))
    )


def _escape_json_for_inline_html(payload: dict[str, Any]) -> str:
    rendered = json.dumps(payload, sort_keys=True)
    return (
        rendered
        .replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
    )
