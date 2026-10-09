# Data sources

## Elevation

[NOAA NCEI ETOPO2022 Global Relief Model](https://www.ncei.noaa.gov/products/etopo-global-relief-model), ice-surface elevation in meters, EGM2008 vertical datum. The build requests stride-4 samples from the 60-arcsecond dataset, yielding 5,400 × 2,700 samples.

[Source subset](https://oceanwatch.pifsc.noaa.gov/erddap/griddap/ETOPO_2022_v1_60s.nc?z[0:4:10799][0:4:21599]) SHA256:

```
9f1180d6cd06f3d1fa7c5539a19faa246ca576d82b5db7aec6c565bcf3274280
```

## Color imagery

[NASA Blue Marble Next Generation](https://science.nasa.gov/earth/earth-observatory/blue-marble-next-generation/base-map/), January 2004, 5,400 × 2,700. Credit: NASA Earth Observatory / NASA Goddard Space Flight Center / Reto Stöckli.

[NASA source image](https://assets.science.nasa.gov/content/dam/science/esd/eo/images/bmng/bmng-base/january/world.200401.3x5400x2700.jpg) SHA256:

```
99f5faad74efe985fbf1714c8be7296ca9999759a1215b65f99b7f1df278dde5
```

[NASA media usage guidance](https://www.nasa.gov/nasa-brand-center/images-and-media/).

## Game inputs

Hearts of Iron IV and its engine/assets belong to their respective rights holders. The repository supplies transformations that operate on a local installation. It does not bundle the executable, decompiled game source, original shader files, or game textures. Generated assets remain local.
