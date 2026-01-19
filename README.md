
# JSR-184 M3G Format
## Brief Evolution History (2003–2009)
JSR-184 `.m3g` specification was approved by the Java Community Process (JCP) in November 2003. It was introduced as the first standardized mobile 3D runtime format (_v1.0_) for J2ME (Java)-driven mobile phone devices, providing a retained-mode scene graph, animation system, binary asset specification for mobile devices with differing hardware implementations, including those produced by Nokia (Symbian SDK) and Sony Ericsson (SE SDK). Through 2005, the .M3G format expanded with additional features (_v1.1_, including fog and depth). HiCorp (JP) implemented Mascot Capsule as a reference JSR-184 execution environment and API validation layer, effectively standardizing runtime behavior across devices for 90% of the Java video games at the time. It is implied that the JSR-184 format corresponds to “Micro3D v2” within the 2003-2005 mobile graphics evolution timeline.

As videogame production pipelines scaled, `.m3g` served as a core intermediate 3D representation rather than a final shipping asset, leading in late 2005 to the introduction of `.mtra` and `.btrac` formats associated with Micro3D v3, which preserved M3G semantics while enabling precompiled model and animation data. This evolution culminated around 2009 with the `.h3t` container (Micro3D v4), formalized under JSR-194, where M3G concepts were compiled into a fixed runtime asset format with scene data and animations resolved during conversion for execution across supported devices.

[Official Java Community Process page for JSR-184 Mobile 3D Graphics API](https://jcp.org/en/jsr/detail?id=184)  
[Official JSR-184 Mobile 3D Graphics API documentation](https://nikita36078.github.io/J2ME_Docs/docs/jsr184/)  
[JSR-184 byte layout and ObjectType ID structure](https://www.j2megame.org/j2meapi/JSR_184_Mobile_3D_Graphics_API_1_1/file-format.html#Fog)
