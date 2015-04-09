'''counts2counts.py - perform transformations on counts tables
==============================================================

:Author: Tom Smith
:Release: $Id$
:Date: |today|
:Tags: Python

Purpose
-------

This scripts provides transformations for counts tables

The methods implemented are

filter
   Output the counts table after applying filtering.

spike
   Output a counts table with in-silico spike-ins. The spike-ins
   can be used to empirically check the power of any of the testing
   methods.

Usage
-----

filtering
+++++++++

    zcat counts.tsv.gz | cgat counts2counts --design-tsv-file=design.tsv
    --filter-min-counts-per-row=1000 --filter-min-counts-per-sample=10000
    --filter-percentile-rowsums=25 > filtered_counts.tsv

spike-ins by row
++++++++++++++++

    zcat counts.tsv.gz | cgat counts2counts
    --design-tsv-file=design.tsv --method="spike" --spike-type="row"
    --spike-maximum=100 --spike-change-bin-width=1
    --spike-initial-bin-width=10 --spike-change-bin-max=10
    --spike-initial-bin-max=10

spike-ins by cluster
++++++++++++++++

    zcat counts.tsv.gz | cgat counts2counts
    --design-tsv-file=design.tsv --method="spike" --spike-type="row"
    --spike-maximum=100 --spike-change-bin-width=1
    --spike-initial-bin-width=10 --spike-change-bin-max=10
    --spike-initial-bin-max=10 --spike-cluster-minimum-size=1
    --spike-cluster-maximum-size=10 --spike-cluster-maximum-width=1


normalize
+++++++++

   zcat counts.tsv.gz | cgat counts2counts.py --method="normalize"
   --normalization-method=deseq-size-factors
   | gzip > normalized.tsv.gz

Input
-----

The input to this script is a counts table containing one item per row
(e.g gene, CpG) and measurements per item in columns.

If creating row-wise spike-ins, it is expected that the first column
will contain an identifier for the row

If creating cluster-wise spike-ins, it is expected that the counts table
will contain columns "contig" and "position" for clustering purposes

The script further requires a design table describing the tests to
be performed. The design table has for columns::

      track   include group   pair
      CW-CD14-R1      0       CD14    0
      CW-CD14-R2      0       CD14    0
      CW-CD14-R3      1       CD14    0
      CW-CD4-R1       1       CD4     0


track
     name of track - should correspond to column header in the counts
     table.
include
     flag to indicate whether or not to include this data
group
     group indicator - experimental group
pair
     pair that sample belongs to (for paired tests) - set to 0 if the
     design is not paired.


Output
------

Command line options
--------------------

filter
+++++++++

Filtering is currently parameterised via 3 options which are performed
in order:

--filter-min-counts-per-row=[int]
    Remove rows where all columns (samples) are below this value

--filter-min-counts-per-sample=[int]
    Remove samples (columns) where the sum of values is lower than this number
    Note that this is performed after filtering rows as described above

--filter-percentile-rowsums=[int]

    Remove rows whose mean value falls below this percentile
    Note that this is perform after the above two filtering steps


spike
++++++

The generation of spike-ins is extensively parameterised:

--spike-type=[row / cluster]

    Spike-ins will be generated by shuffling rows or identifying
    clusters of rows and shuffling subclusters.

--difference-method=[logfold / relative]

    Difference will be calculated as "logfold" (log2(group2/group1))
    or "relative" (group2 - group1).

--spike-change-bin-min=[int]
--spike-change-bin-max=[int]
--spike-change-bin-width=[int]

    Min, max and width values may be set for the change values and
    similarly for the initial values. If spike-type=cluster, the min,
    max and width of the subclusters can also be similarly defined.

--spike-output-method=[seperate / append]

    Spike-ins will be outputted seperately or appended to the end of
    the original counts table.

--spike-iterations=[int]

    Defines how many iterations of random shuffling should be performed.

--spike-shuffle-column-suffix=[string]
--spike-keep-column-suffix=[string]

    Defines a suffix for columns to be suffled and additional columns that
    should be keep alongside the shuffling columns for each sample. For
    example, with methylation data, one may wish to shuffle columns
    containing the percentage methylation (0-100) and retain additional
    columns containing the counts of methylated/unmethylated

'''

import sys
import os
import pandas as pd
import numpy as np

try:
    import CGAT.Experiment as E
    import CGAT.Counts as Counts
    import CGAT.Expression as Expression
    import CGAT.IOTools as IOTools
except ImportError:
    import Experiment as E
    import Expression
    import Counts
    import IOTools


def main(argv=None):
    """script main.

    parses command line options in sys.argv, unless *argv* is given.
    """

    if not argv:
        argv = sys.argv

    # setup command line parser
    parser = E.OptionParser(version="%prog version: $Id$",
                            usage=globals()["__doc__"])

    parser.add_option("-d", "--design-tsv-file", dest="input_filename_design",
                      type="string",
                      help="input file with experimental design "
                      "[default=%default].")

    parser.add_option("-m", "--method", dest="method", type="choice",
                      choices=("filter", "spike", "normalize"),
                      help="differential expression method to apply "
                      "[default=%default].")

    parser.add_option("--filter-min-counts-per-row",
                      dest="filter_min_counts_per_row",
                      type="int",
                      help="remove rows with less than this "
                      "number of counts in total [default=%default].")

    parser.add_option("--filter-min-counts-per-sample",
                      dest="filter_min_counts_per_sample",
                      type="int",
                      help="remove samples with a maximum count per sample of "
                      "less than this numer   [default=%default].")

    parser.add_option("--filter-percentile-rowsums",
                      dest="filter_percentile_rowsums",
                      type="int",
                      help="remove percent of rows with "
                      "lowest total counts [default=%default].")

    parser.add_option("--spike-change-bin-min", dest="min_cbin",
                      type="float",
                      help="minimum bin for change bins [default=%default].")

    parser.add_option("--spike-change-bin-max", dest="max_cbin",
                      type="float",
                      help="maximum bin for change bins [default=%default].")

    parser.add_option("--spike-change-bin-width", dest="width_cbin",
                      type="float",
                      help="bin width for change bins [default=%default].")

    parser.add_option("--spike-initial-bin-min", dest="min_ibin",
                      type="float",
                      help="minimum bin for initial bins[default=%default].")

    parser.add_option("--spike-initial-bin-max", dest="max_ibin",
                      type="float",
                      help="maximum bin for intitial bins[default=%default].")

    parser.add_option("--spike-initial-bin-width", dest="width_ibin",
                      type="float",
                      help="bin width intitial bins[default=%default].")

    parser.add_option("--spike-minimum", dest="min_spike",
                      type="int",
                      help="minimum number of spike-ins required within each bin\
                      [default=%default].")

    parser.add_option("--spike-maximum", dest="max_spike",
                      type="int",
                      help="maximum number of spike-ins allowed within each bin\
                      [default=%default].")

    parser.add_option("--spike-difference-method", dest="difference",
                      type="choice", choices=("relative", "logfold"),
                      help="method to use for calculating difference\
                      [default=%default].")

    parser.add_option("--spike-iterations", dest="iterations", type="int",
                      help="number of iterations to generate spike-ins\
                      [default=%default].")

    parser.add_option("--spike-cluster-maximum-distance",
                      dest="cluster_max_distance", type="int",
                      help="maximum distance between adjacent loci in cluster\
                      [default=%default].")

    parser.add_option("--spike-cluster-minimum-size",
                      dest="cluster_min_size", type="int",
                      help="minimum number of loci required per cluster\
                      [default=%default].")

    parser.add_option("--spike-type",
                      dest="spike_type", type="choice",
                      choices=("row", "cluster"),
                      help="spike in type [default=%default].")

    parser.add_option("--spike-subcluster-min-size",
                      dest="min_sbin", type="int",
                      help="minimum size of subcluster\
                      [default=%default].")

    parser.add_option("--spike-subcluster-max-size",
                      dest="max_sbin", type="int",
                      help="maximum size of subcluster\
                      [default=%default].")

    parser.add_option("--spike-subcluster-bin-width",
                      dest="width_sbin", type="int",
                      help="bin width for subcluster size\
                      [default=%default].")

    parser.add_option("--spike-output-method",
                      dest="output_method", type="choice",
                      choices=("append", "seperate"),
                      help="defines whether the spike-ins should be appended\
                      to the original table or seperately [default=%default].")

    parser.add_option("--spike-shuffle-column-suffix",
                      dest="shuffle_suffix", type="string",
                      help="the suffix of the columns which are to be shuffled\
                      [default=%default].")

    parser.add_option("--spike-keep-column-suffix",
                      dest="keep_suffix", type="string",
                      help="a list of suffixes for the columns which are to be\
                      keep along with the shuffled columns[default=%default].")

    parser.add_option("--normalization-method",
                      dest="normalization_method", type="choice",
                      choices=("deseq-size-factors", "million-counts"),
                      help="normalization method to apply [%default]")

    parser.add_option("-t", "--tags-tsv-file", dest="input_filename_tags",
                      type="string",
                      help="input file with tag counts [default=%default].")

    parser.set_defaults(
        input_filename_tags="-",
        method="filter",
        filter_min_counts_per_row=None,
        filter_min_counts_per_sample=None,
        filter_percentile_rowsums=None,
        output_method="seperate",
        difference="logfold",
        spike_type="row",
        min_cbin=0,
        max_cbin=100,
        width_cbin=100,
        min_ibin=0,
        max_ibin=100,
        width_ibin=100,
        max_spike=100,
        min_spike=None,
        iterations=1,
        cluster_max_distance=100,
        cluster_min_size=10,
        min_sbin=1,
        max_sbin=1,
        width_sbin=1,
        shuffle_suffix=None,
        keep_suffix=None,
        normalization_method="deseq-size-factors",
    )

    # add common options (-h/--help, ...) and parse command line
    (options, args) = E.Start(parser, argv=argv, add_output_options=True)

    # load
    if options.keep_suffix:
        # if using suffix, loadTagDataPandas will throw an error as it
        # looks for column names which exactly match the design
        # "tracks" need to write function in Counts.py to handle
        # counts table and design table + suffix
        counts = pd.read_csv(sys.stdin, sep="\t",  comment="#")
        inf = IOTools.openFile(options.input_filename_design)
        design = pd.read_csv(inf, sep="\t", index_col=0)
        inf.close()
        design = design[design["include"] != 0]

        if options.method in ("filter", "spike"):
            if options.input_filename_design is None:
                raise ValueError("method '%s' requires a design file" %
                                 options.method)

    else:
        # create Counts object
        # TS if spike type is cluster, need to keep "contig" and "position"
        # columns out of index
        if options.spike_type == "cluster":
            index = None,
        else:
            index = 0

        if options.input_filename_tags == "-":
            counts = Counts.Counts(pd.io.parsers.read_csv(
                sys.stdin, sep="\t", index_col=index, comment="#"))
        else:
            counts = Counts.Counts(
                IOTools.openFile(options.input_filename_tags, "r"),
                sep="\t", index_col=index, comment="#")

        # TS normalization doesn't require a design table
        if not options.method == "normalize":

            assert options.input_filename_design and os.path.exists(
                options.input_filename_design)

            # create Design object
            design = Expression.ExpDesign(
                pd.read_csv(
                    IOTools.openFile(options.input_filename_design, "r"),
                    sep="\t", index_col=0, comment="#"))

            design.getAttributes()

    if options.method == "filter":

        assert (options.filter_min_counts_per_sample is not None or
                options.filter_min_counts_per_row is not None or
                options.filter_percentile_rowsums is not None), \
            "no filtering parameters have been suplied"

        # filter
        # remove sample with low counts
        if options.filter_min_counts_per_sample:
                counts.removeSamples(
                    min_counts_per_sample=options.filter_min_counts_per_sample)

        # remove observations with low counts
        if options.filter_min_counts_per_row:
                counts.removeObservationsFreq(
                    min_counts_per_row=options.filter_min_counts_per_row)

        # remove bottom percentile of observations
        if options.filter_percentile_rowsums:
                counts.removeObservationsPerc(
                    percentile_rowsums=options.filter_percentile_rowsums)

        nobservations, nsamples = counts.table.shape

        if nobservations == 0:
            E.warn("no observations remaining after filtering- no output")
            return

        if nsamples == 0:
            E.warn("no samples remain after filtering - no output")
            return

        # write out
        counts.table.to_csv(options.stdout, sep="\t", header=True)

    elif options.method == "normalize":

        counts.normalise(method=options.normalization_method)

        # write out
        counts.table.to_csv(options.stdout, sep="\t", header=True)

    elif options.method == "spike":

        # check parameters are sensible and set parameters where they
        # are not explicitly set
        if not options.min_spike:
            E.info("setting minimum number of spikes per bin to equal"
                   "maximum number of spikes per bin (%s)" % options.max_spike)
            options.min_spike = options.max_spike

        if options.spike_type == "cluster":

            assert options.max_sbin <= options.cluster_min_size, \
                ("max size of subscluster: %s is greater than min size of"
                 "cluster: %s" % (options.max_sbin, options.cluster_min_size))

            counts_columns = set(counts.table.columns.values.tolist())

            assert ("contig" in counts_columns and
                    "position" in counts_columns), \
                ("cluster analysis requires columns named 'contig' and"
                 "'position' in the dataframe")

            counts.sort(sort_columns=["contig", "position"], reset_index=True)

        # restrict design table to first pair only
        design.firstPairOnly()

        # get dictionaries to map group members to column names
        # use different methods depending on whether suffixes are supplied
        if options.keep_suffix:
            g_to_keep_tracks, g_to_spike_tracks = design.mapGroupsSuffix(
                options.shuffle_suffix, options.keep_suffix)
        else:
            # if no suffixes supplied, spike and keep tracks are the same
            g_to_track = design.mapGroups()
            g_to_spike_tracks, g_to_keep_tracks = (g_to_track, g_to_track)

        # set up numpy arrays for change and initial values
        change_bins = np.arange(options.min_cbin, options.max_cbin,
                                options.width_cbin)
        initial_bins = np.arange(options.min_ibin, options.max_ibin,
                                 options.width_ibin)

        E.info("Column boundaries are: %s" % str(change_bins))
        E.info("Row boundaries are: %s" % str(initial_bins))

        # shuffle rows/clusters
        if options.spike_type == "cluster":
            E.info("looking for clusters...")
            clusters_dict = Counts.findClusters(
                counts_sort, options.cluster_max_distance,
                options.cluster_min_size, g_to_spike_tracks, groups)
            if len(clusters_dict) == 0:
                raise Exception("no clusters were found, check parameters")

            E.info("shuffling subcluster regions...")
            output_indices, counts = Counts.shuffleCluster(
                initial_bins, change_bins, g_to_spike_tracks, groups,
                options.difference, options.max_spike,
                options.iterations, clusters_dict,
                options.max_sbin, options.min_sbin, options.width_sbin)

        elif options.spike_type == "row":

            E.info("shuffling rows...")
            output_indices, bin_counts = counts.shuffleRows(
                options.min_cbin, options.max_cbin, options.width_cbin,
                options.min_ibin, options.max_ibin, options.width_ibin,
                g_to_spike_tracks, design.groups, options.difference,
                options.max_spike, options.iterations)

        filled_bins = Counts.thresholdBins(output_indices, bin_counts,
                                           options.min_spike)

        assert len(filled_bins) > 0, "No bins contained enough spike-ins"

        # write out
        counts.outputSpikes(
            filled_bins,
            g_to_keep_tracks, design.groups,
            output_method=options.output_method,
            spike_type=options.spike_type,
            min_cbin=options.min_cbin,
            width_cbin=options.width_cbin,
            max_cbin=options.max_cbin,
            min_ibin=options.min_ibin,
            width_ibin=options.width_ibin,
            max_ibin=options.max_ibin,
            min_sbin=options.min_sbin,
            width_sbin=options.width_sbin,
            max_sbin=options.max_sbin,)

    E.Stop()

if __name__ == "__main__":
    sys.exit(main(sys.argv))
