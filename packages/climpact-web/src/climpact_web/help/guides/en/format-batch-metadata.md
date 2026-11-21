title: Batch metadata file format
summary: A text file with a header row, then one line per station: its file name, latitude, longitude and the index settings, in 12 columns. It is the batch metadata file of Climpact for R, so its files work unchanged.

``` { #example }
station_file	latitude	longitude	wsdin	csdin	Tb_HDD	Tb_CDD	Tb_GDD	rxnday	rnnmm	txtn	SPEI
sydney_a.txt	-33.86	151.21	3	3	18	18	10	3	30	2	24
sydney_b.txt	-33.86	151.21	3	3	18	18	10	3	30	2	24
```

[Download the sample metadata file](url:batch:sample_metadata).

## Columns {#columns}

The 12 columns, in this order:

| Column | Meaning | Index |
| --- | --- | --- |
| `station_file` | the station file's name, without any folder | – |
| `latitude`, `longitude` | decimal degrees, negative south and west | GSL, heatwaves |
| `wsdin` | days in a row, 1 to 10 | [WSDId](index:wsdid) |
| `csdin` | days in a row, 1 to 10 | [CSDId](index:csdid) |
| `Tb_HDD` | base temperature, °C | [HDDheat](index:hddheatn) |
| `Tb_CDD` | base temperature, °C | [CDDcold](index:cddcoldn) |
| `Tb_GDD` | base temperature, °C | [GDDgrow](index:gddgrown) |
| `rxnday` | days, 1 or more | [Rxdday](index:rxdday) |
| `rnnmm` | precipitation, mm, 0 or more | [Rnnmm](index:rnnmm) |
| `txtn` | days in a row, 1 or more | [TXdTNd](index:txdtnd), [TXbdTNbd](index:txbdtnbd) |
| `SPEI` | extra time scale, months | [SPI](index:spi), [SPEI](index:spei) |

- Values separated by spaces or tabs.
- The first line holds the column names; lines starting with `#` are ignored.
- There is no column for a custom index.

## Station files {#station-files}

Each line names a [station file](guide:format-station-file). Name each file **exactly** as
in the `station_file` column, including capitals and the extension. On this site, choose
the files and the metadata file together, or put them in one zip; on the command line,
give the folder that holds the files (`climpact batch` in the
[command line](guide:command-line#batch)).

How a batch runs and how to read its results is in [Batch processing](guide:batch).
