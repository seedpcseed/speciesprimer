#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Fri Jul 16 18:36:12 2021

@author: ags-bioinfo
"""

#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import time
import shutil
import logging
import fnmatch
import multiprocessing
import pandas as pd
import numpy as np
from datetime import timedelta
from Bio import SeqIO
from Bio.Seq import Seq
from Bio.SeqRecord import SeqRecord


# paths
pipe_dir = "/home/ags-bioinfo/blastdb/primerdesign/speciesprimer/pipeline"
dict_path = os.path.join(pipe_dir, "dictionaries")
tmp_db_path = os.path.join(pipe_dir, 'tmp_config.json')
if not pipe_dir in sys.path:
    sys.path.append(pipe_dir)

from scripts.configuration import errors
from scripts.configuration import RunConfig
from scripts.configuration import PipelineStatsCollector
from basicfunctions import GeneralFunctions as G
from basicfunctions import HelperFunctions as H
from basicfunctions import ParallelFunctions as P
from basicfunctions import BlastDBError


class BlastPrep():
    def __init__(self, directory, input_records, name, maxpartsize):
        self.list_dict = {}
        self.input_records = input_records
        self.maxpartsize = maxpartsize
        self.filename = name
        self.directory = directory

    def create_listdict(self):
        groups = len(self.input_records) // self.maxpartsize
        if len(self.input_records) % self.maxpartsize > 0:
            groups = groups + 1
        for i in range(0, groups):
            if i not in self.list_dict.keys():
                self.list_dict.update({i: []})

    def get_equalgroups(self):
        self.input_records.sort(key=lambda x: int(len(x.seq)), reverse=True)
        list_start = 0
        list_end = len(self.input_records) - 1
        removed_key = []
        key = 0
        i = list_start
        while key in self.list_dict.keys():
            if key in removed_key:
                key = key + 1
            else:
                item = self.input_records[i]
                if len(self.list_dict[key]) < self.maxpartsize:
                    self.list_dict[key].append(item)
                    key = key + 1
                    if key not in self.list_dict.keys():
                        key = 0
                    if i == list_end:
                        break
                    else:
                        i = i + 1
                else:
                    removed_key.append(key)

    def write_blastinput(self):
        for key in self.list_dict.keys():
            if len(self.list_dict[key]) > 0:
                file_name = os.path.join(
                    self.directory, self.filename + ".part-"+str(key))
                SeqIO.write(self.list_dict[key], file_name, "fasta")


    def run_blastprep(self):
        G.logger("Run: run_blastprep - Preparing files for BLAST")
        print("\nPreparing files for BLAST")
        self.create_listdict()
        self.get_equalgroups()
        cores = multiprocessing.cpu_count()
        self.write_blastinput()
        return cores


class Blast(RunConfig):
    def __init__(self, configuration, directory, mode):
        print("Start BLAST")
        RunConfig.__init__(self, configuration)
        self.directory = directory
        self.mode = mode

    def get_blast_cmd(self, blastfile, filename, cores):
        fmt_file = os.path.join(dict_path, "blastfmt6.csv")
        fmts = pd.read_csv(fmt_file, header=None).dropna()
        blast_fmt = " ".join(["6"] + list(fmts[0]))

        if self.mode == "quality_control":
            blast_cmd = [
                "blastn", "-task", "megablast", "-num_threads",
                str(cores), "-query", blastfile, "-max_target_seqs", "5",
                "-max_hsps", "1", "-out", filename, "-outfmt", blast_fmt]

        if self.mode == "conserved":
            blast_cmd = [
                "blastn", "-task", "dc-megablast", "-num_threads",
                str(cores), "-query", blastfile, "-max_target_seqs",
                "2000", "-max_hsps", "1", "-out", filename, "-outfmt", blast_fmt]

        if self.mode == "primer":
            blast_cmd = [
                "blastn", "-task", "blastn-short", "-num_threads",
                str(cores), "-query", blastfile,
                "-evalue", "500", "-out", filename, "-outfmt", blast_fmt]

        blast_cmd.append("-db")
        if self.config.customdb:
            blast_cmd.append(self.config.customdb)
        else:
            blast_cmd.append("nt")

        return blast_cmd

    def run_blast(self, name, use_cores):
        G.logger("Run: run_blast - Start BLAST")
        blast_files = [f for f in os.listdir(directory) if ".part-" in f]
        blastfiles.sort(key=lambda x: int(x.split("part-")[1]))
        start = time.time()
        os.chdir(self.directory)
        for blastfile in blastfiles:
            part = str(blastfile).split("-")[1]
            filename = name + "_" + part + "_results.csv"
            results_path = os.path.join(self.directory, filename)
            if self.mode == "quality_control":
                blast_cmd = self.get_blast_cmd(
                    blastfile, filename, use_cores)
            elif not os.path.isfile(results_path):
                blast_cmd = self.get_blast_cmd(
                    blastfile, filename, use_cores)
            else:
                if os.stat(results_path).st_size == 0:
                    blast_cmd = self.get_blast_cmd(
                        blastfile, filename, use_cores)
                else:
                    blast_cmd = False
                    G.comm_log("> Skip Blast step for " + blastfile)
            if blast_cmd:
                try:
                    G.run_subprocess(blast_cmd)
                except (KeyboardInterrupt, SystemExit):
                    G.keyexit_rollback(
                        "BLAST search", dp=self.directory, fn=filename)
                    raise

        duration = time.time() - start
        G.comm_log(
            "> Blast duration: "
            + str(timedelta(seconds=duration)).split(".")[0])
        os.chdir(self.target_dir)


class BlastParser(RunConfig):
    def __init__(self, configuration, results="conserved"):
        RunConfig.__init__(self, configuration)
        self.exception = configuration.exception
        self.evalue = self.config.evalue
        self.nuc_identity = self.config.nuc_identity
        self.nontargetlist = configuration.nontargetlist
        self.mode = results
        self.start = time.time()
        self.maxgroupsize = 25000
        self.unlisted_spec = []

    def check_blastdb_errors(self, blastdf, filename):
        if len(blastdf.index) == 0:
            error_msg = " ".join([
                "A problem with the BLAST results file",
                filename, "was detected.",
                "Please check if the file was removed and start the run again"])

        elif len(blastdf[blastdf["Subject Seq-id"].str.contains("gnl|BL_ORD_ID|", regex=False)]) > 0:
            error_msg = (
                "Problem with custom DB, Please use the '-parse_seqids'"
                " option for the makeblastdb command")

        elif len(blastdf[blastdf["Subject Title"].str.contains("No definition line", regex=False)]) > 0:
            error_msg = (
                "Error: No definition line in Subject Title"
                "\nData is missing in the custom BLAST DB. At least "
                "a unique sequence identifier and the species name "
                "is required for each entry.\nExpected format: "
                ">seqid species name optional description")
        else:
            return

        logging.error("> " + error_msg, exc_info=True)
        errors.append([self.target, error_msg])
        os.remove(filename)
        print("removed " + filename)
        raise BlastDBError(error_msg)

    def get_excluded_gis(self):
        excluded_gis = []
        gi_file = os.path.join(self.config_dir, "no_blast.gi")
        if os.path.isfile(gi_file):
            if os.stat(gi_file).st_size > 0:
                with open(gi_file, "r") as f:
                    for line in f:
                        gi = line.strip()
                        excluded_gis.append(str(gi))
        return excluded_gis

    def get_exceptions(self):
        target_sp = " ".join(
            [
                self.target.split("_")[0],
                H.subspecies_handler(self.target, mode="space")])
        exceptions = [target_sp]
        if self.exception != []:
            for item in self.exception:
                exception = ' '.join(item.split("_"))
                if exception not in exceptions:
                    exceptions.append(exception)
        return exceptions

    def get_species_names_from_title(self, df):
        if self.config.virus is True:
            df.loc[:, "Species"] = df.loc[:, "Subject Title"].str.split(",").str[0]
        else:
            subsp_filter = df["Subject Title"].str.contains("|".join(["subsp.", "pv."]))
            df.loc[
                subsp_filter, "Species"
                ] = df.loc[
                            subsp_filter, "Subject Title"
                                ].str.split(" ").str[0:4].apply(
                                            lambda x: ' '.join(x))
            df.loc[
                ~subsp_filter, "Species"
                ] = df.loc[
                            ~subsp_filter, "Subject Title"
                                ].str.split(" ").str[0:2].apply(
                                            lambda x: ' '.join(x))
        return df

    def quality_control(self, blastdf, exceptions):
        blastdf = blastdf.sort_values(
            ["Query Seq-id", "Bit score"], ascending=False)
        blastdf = blastdf.drop_duplicates(["Query Seq-id"])
        mask = blastdf["Species"].str.contains("|".join(exceptions))
        blastdf.loc[mask, "QC status"] = "passed QC"
        blastdf.loc[~mask, "QC status"] = "failed QC"
        blastdf["Target species"] = exceptions[0]
        QC_results = blastdf[[
                "Query Seq-id", "Subject GI", "Subject accession",
                "Species", "Target species", "QC status"]]
        return QC_results

    def offtarget_sequences(self, offtarget_hits):
        if self.config.nuc_identity > 0:
            offtarget_hits = offtarget_hits[
                offtarget_hits[
                    'Percentage of identical matches'] >= self.config.nuc_identity]

        offtarget_hits = offtarget_hits[
                offtarget_hits['Expect value'] <= self.config.evalue]

        partialseqs = self.check_seq_ends(offtarget_hits)

        offtarget_summary = offtarget_hits[[
            "Query Seq-id", "Species", "Subject GI", "Subject accession",
            'Percentage of identical matches', 'Expect value', 'Bit score']]
        return offtarget_summary, partialseqs


    def parse_blastrecords(self, blastdf, excluded_gis, exceptions):
        # remove excluded sequences from the results
        blastdf = blastdf[~blastdf["Subject GI"].isin(excluded_gis)]
        blastdf = blastdf[~blastdf["Subject accession"].isin(excluded_gis)]
        # Extract species names from title
        blastdf = self.get_species_names_from_title(blastdf)
        if self.mode == "quality_control":
            QC_results = self.quality_control(blastdf, exceptions)
            partialseqs = pd.DataFrame()
            return QC_results, partialseqs

        offtarget_hits = blastdf[~blastdf["Species"].isin(exceptions)]
        if self.config.nolist is False:
            offtarget_filter = (offtarget_hits["Species"].str.contains("|".join(self.nontargetlist)))
            notonlist = offtarget_hits[~offtarget_filter]
            offtarget_hits = offtarget_hits[offtarget_filter]
            self.unlisted_spec.extend(notonlist["Species"].unique())

        if self.mode == "conserved":
            offtarget_summary, partialseqs = self.offtarget_sequences(offtarget_hits)

        if self.mode == "primer":
            partialseqs = pd.DataFrame()
            offtarget_summary = offtarget_hits[[
                "Query Seq-id", "Species", "Subject GI", "Subject accession",
                "Start of alignment in subject", "End of alignment in subject",
                "Subject sequence length"]]

        return offtarget_summary, partialseqs

    def check_seq_ends(self, offtarget):
        # Filter non-aligned endings
        offtarget.loc[:, 'overhang'] = (
                            offtarget.loc[
                                :,'Query sequence length'
                            ] - offtarget.loc[:, 'End of alignment in query'])

        partials_max = offtarget.sort_values(
            'overhang', ascending=True).drop_duplicates(['Query Seq-id'])
        keep_max = partials_max[partials_max['overhang'] >= self.config.minsize]

        partials_min = offtarget.sort_values(
                'Start of alignment in query', ascending=True
            ).drop_duplicates(['Query Seq-id'])
        keep_min = partials_min[
                partials_min[
                    "Start of alignment in query"] >= self.config.minsize]
        keep_min = keep_min.assign(Start=1)

        # Write sequence range data
        mindata = keep_min[['Query Seq-id', "Start", "Start of alignment in query"]]
        maxdata = keep_max[['Query Seq-id', 'End of alignment in query', 'Query sequence length']]
        mindata.columns = ["ID", "Start", "Stop"]
        maxdata.columns = ["ID", "Start", "Stop"]

        partial_seqs = pd.concat([mindata, maxdata], sort=False)

        return partial_seqs

    def create_blastdf(self, filename, header):
        try:
            blastdf = pd.read_csv(filename, sep="\t", header=None)
            blastdf.columns = header
            blastdf = blastdf.astype(
                {"Subject GI": str, "Subject accession": str})
        except pd.errors.EmptyDataError:
            blastdf = pd.DataFrame()
        self.check_blastdb_errors(blastdf, filename)
        return blastdf

    def parse_results(self, blast_dir):
        offtarget_dfs = []
        partial_dfs = []
        blastresults = [
            os.path.join(blast_dir, f) for f in os.listdir(blast_dir)
            if f.endswith("results.csv")]
        blastresults.sort()

        exceptions = self.get_exceptions()
        excluded_gis = self.get_excluded_gis()
        print("Excluded GI(s):", excluded_gis)

        fmt_file = os.path.join(dict_path, "blastfmt6.csv")
        header = list(pd.read_csv(fmt_file, header=None)[1].dropna())

        print("open BLAST result files")
        for i, filename in enumerate(blastresults):
            print(str(i+1) + "/" + str(len(blastresults)))

            blastdf = self.create_blastdf(filename, header)
            offtarget, partialseqs = self.parse_blastrecords(
                blastdf, excluded_gis, exceptions)

            offtarget_dfs.append(offtarget)
            partial_dfs.append(partialseqs)

        offtarget = pd.concat(offtarget_dfs)
        partial = pd.concat(partial_dfs)

        return offtarget, partial

    def write_mostcommonhits(self, df):
        to_file = os.path.join(self.blast_dir, "mostcommonhits.csv")
        total = len(df.index)
        queries = len(set(df["Query Seq-id"]))
        mostcommon = pd.DataFrame(df.drop_duplicates(["Query Seq-id", "Species"])["Species"].value_counts())
        mostcommon.index.name ="Species"
        mostcommon.columns = ["BLAST hits [count]"]
        mostcommon["BLAST hits [% of queries]"] = mostcommon["BLAST hits [count]"].apply(lambda x: round(100/queries*x, 1))
        mostcommon.sort_values("BLAST hits [% of queries]", ascending=False, inplace=True)
        f_head = str("Total BLAST hits,Number of queries\n" + str(total) + "," + str(queries) + "\n")
        with open(to_file, "w") as f:
            f.write(f_head)
        mostcommon.to_csv(to_file, mode='a')


    def write_primer3_input(self, offtarget_seqs):
        G.create_directory(self.primer_dir)
        file_path = os.path.join(self.primer_dir, "primer3_input")
        controlfile_path = os.path.join(self.coregene_dir, ".primer3_input")
        conserved_seqs = os.path.join(blast_dir, "conserved_seqs.fas")
        conserved_seq_dict = SeqIO.to_dict(SeqIO.parse(conserved_seqs, "fasta"))
        conserved = list(set(conserved_seq_dict.keys()) - set(offtarget_seqs))
        selected_recs = [conserved_seq_dict[k] for k in conserved]

        if self.config.probe is True:
            probe = "\nPRIMER_PICK_INTERNAL_OLIGO=1"
        else:
            probe = ""

        with open(file_path, "w") as f:
            for rec in selected_recs:
                f.write(
                        "SEQUENCE_ID=" + rec.id + "\nSEQUENCE_TEMPLATE="
                        + str(rec.seq)
                        + "\nPRIMER_PRODUCT_SIZE_RANGE="
                        + str(self.config.minsize) + "-"
                        + str(self.config.maxsize) + probe + "\n=\n")

            partial_file = os.path.join(self.blast_dir, "partialseqs.csv")
            if os.path.isfile(partial_file):
                parts = pd.read_csv(partial_file, header=None)
                seq_id = parts[0].to_list()
                start = parts[1].to_list()
                end = parts[2].to_list()
                for i, idx in enumerate(seq_id):
                    f.write(
                        "SEQUENCE_ID=" + idx + "\nSEQUENCE_TEMPLATE="
                        + str(conserved_seq_dict[idx].seq)[start[i]:end[i]]
                        + "\nPRIMER_PRODUCT_SIZE_RANGE="
                        + str(self.config.minsize) + "-"
                        + str(self.config.maxsize) + probe + "\n=\n")
        self.changed_primer3_input(file_path, controlfile_path)


    def interpret_blastresults(self, blast_dir, offtarget, partial):
        if self.mode == "quality_control":
            if offtarget.empty:
                G.comm_log("> No Quality Control results found")
                errors.append([self.target, error_msg])
            else:
                qc_dir = os.path.basename(blast_dir)
                fp = os.path.join(blast_dir, qc_dir + "_report.csv")
                offtarget.to_csv(fp, index=False)

        if partial.empty is False:
            part_file = os.path.join(blast_dir, "partialseqs.csv")
            partial.to_csv(part_file, index=False, header=False)

        fp = os.path.join(blast_dir, "offtarget_summary.csv")
        offtarget.to_csv(fp, index=False)

        if self.mode == "conserved":
            self.write_mostcommonhits(offtarget)
            offtarget_seqs = offtarget['Query Seq-id'].unique()
            self.write_primer3_input(offtarget_seqs)
            self.write_mostcommonhits(offtarget)

    def changed_primer3_input(self, file_path, controlfile_path):

        def find_difference():
            new = []
            old = []
            with open(file_path) as n:
                for line in n:
                    if "SEQUENCE_ID=" in line:
                        if line.strip() not in new:
                            new.append(line.strip())
                    if "PRIMER_PICK_INTERNAL_OLIGO=" in line:
                        if line.strip() not in new:
                            new.append(line.strip())

            with open(controlfile_path) as o:
                for line in o:
                    if "SEQUENCE_ID=" in line:
                        if line.strip() not in old:
                            old.append(line.strip())
                    if "PRIMER_PICK_INTERNAL_OLIGO=" in line:
                        if line.strip() not in old:
                            old.append(line.strip())

            diff = list(set(new) ^ set(old))
            return diff

        if os.path.isfile(controlfile_path):
            diff = find_difference()
            if len(diff) > 0:
                info1 = (
                    "Due to changed settings primer design "
                    "and quality control will start from scratch")
                info2 = "Differences in primer3 input:"
                for info in [info1, info2, diff]:
                    G.comm_log(info)
                if os.path.isdir(self.primer_dir):
                    G.comm_log("Delete primer directory")
                    shutil.rmtree(self.primer_dir)
                G.create_directory(self.primer_dir)
                shutil.copy(file_path, controlfile_path)
        else:
            shutil.copy(file_path, controlfile_path)



    def run_blastparser(self):
        if self.mode == "primer":
            print("Start primer blast parser")
            offtarget = self.bp_parse_results(self.primerblast_dir)
            db_seqs = self.find_primerbinding_offtarget_seqs(offtarget)
            self.get_primerBLAST_DBIDS(db_seqs)
            self.write_nontarget_sequences()

            duration = time.time() - self.start
            G.comm_log(
                "> Primer blast parser time: "
                + str(timedelta(seconds=duration)).split(".")[0])
        else:
            specific_ids = self.bp_parse_results(self.blast_dir)
            self.write_primer3_input(specific_ids)
            duration = time.time() - self.start
            msg = ("species specific conserved sequences: "
                    + str(len(specific_ids)))
            G.comm_log(
                "> Blast parser time: "
                + str(timedelta(seconds=duration)).split(".")[0])
            print(timedelta(seconds=duration))
            G.comm_log(msg)
            PipelineStatsCollector(self.config).write_stat(msg)

            if len(specific_ids) == 0:
                msg = "> No conserved sequences without non-target match found"
                G.comm_log(msg)
                errors.append([self.target, msg])
                return 1

            return 0

    def main(self):
        qc_gene = "rRNA"
        #qc_dir = os.path.join(self.genomedata_dir, qc_gene + "_QC")
        blast_dir = self.blast_dir
        offtarget, partial = self.parse_results(blast_dir)
        self.interpret_blastresults(blast_dir, offtarget, partial)

    def find_primerbinding_offtarget_seqs(self, df):
        df.loc[:, "Primer pair"] = df.loc[:, "Query Seq-id"].str.split("_").str[0:-1].apply(
                                                                        lambda x: '_'.join(x))
        df.sort_values(['Start of alignment in subject'], inplace=True)

        fwd_df = df[df["Query Seq-id"].str.endswith("_F")]
        rev_df =  df[df["Query Seq-id"].str.endswith("_R")]
        int_df = pd.merge(
                    fwd_df, rev_df, how ='inner',
                    on =['Subject accession', 'Primer pair'], suffixes=("_F", "_R"))

        f = int_df[[
            'Subject accession', 'Start of alignment in subject_F',
            'End of alignment in subject_F', 'Subject sequence length_F']]
        r = int_df[[
            'Subject accession', 'Start of alignment in subject_R',
            'End of alignment in subject_R', 'Subject sequence length_R']]
        std_cols = [
            'Subject accession', 'Start of alignment in subject',
            'End of alignment in subject', 'Subject sequence length']

        f.columns, r.columns = std_cols, std_cols
        common = pd.concat([f, r], sort=False)
        common.reset_index(drop=True, inplace=True)
        return common

    def get_primerBLAST_DBIDS(self, offtarget):
        print("\nGet sequence accessions of BLAST hits\n")
        G.logger("> Get sequence accessions of BLAST hits")
        G.create_directory(self.primer_qc_dir)
        overhang=2000
        output_path = os.path.join(self.primer_qc_dir, "primerBLAST_DBIDS.csv")
        if os.path.isfile(output_path):
            return 0
        # data manipulation
        strandfilter = offtarget['Start of alignment in subject'] > offtarget['End of alignment in subject']
        offtarget.loc[strandfilter, "Start overhang"] = offtarget.loc[strandfilter, 'End of alignment in subject'] - overhang
        offtarget.loc[~strandfilter, "Start overhang"] = offtarget.loc[~strandfilter,'Start of alignment in subject'] - overhang
        offtarget.loc[strandfilter, "End overhang"] = offtarget.loc[strandfilter, 'End of alignment in subject'] + overhang
        offtarget.loc[~strandfilter, "End overhang"] = offtarget.loc[~strandfilter,'Start of alignment in subject'] + overhang

        overfilter = offtarget["End overhang"] > offtarget['Subject sequence length']
        offtarget.loc[overfilter, "End overhang"] = offtarget.loc[overfilter, 'Subject sequence length']
        lowfilter = offtarget["Start overhang"] < 1
        offtarget.loc[lowfilter, "Start overhang"] = 1
        # datatype to int
        offtarget["Start overhang"] = offtarget["Start overhang"].astype('Int64')
        offtarget["End overhang"] = offtarget["End overhang"].astype('Int64')

        # data binning
        max_range = offtarget["End overhang"].max()
        stepsize = self.config.maxsize + overhang*2 + 1
        collection = []
        for i in range(1, max_range,  stepsize):
            j = i + overhang*2 + self.config.maxsize
            sub = offtarget[offtarget["Start overhang"].between(i, j, inclusive=True)]
            mini = sub.groupby(["Subject accession"])["Start overhang"].min()
            maxi = sub.groupby(["Subject accession"])["End overhang"].max()
            submax = pd.concat([mini, maxi], axis=1)
            submax.columns = ["Start", "Stop"]
            submax.sort_values(["Start", "Stop"], inplace=True, ascending=False)
            submax.drop_duplicates(inplace=True)
            collection.append(submax)

        results = pd.concat(collection)

        if len(results.index) == 0:
            msg = (
                "Error did not find any sequences for non-target DB. "
                + "Please check the species list and/or BLAST database")
            print(msg)
            G.logger("> " + msg)
            errors.append([self.target, msg])
            return 1

        results.index.name = "accession"
        results.to_csv(output_path, header=None)
        return 0

    def write_sequences(self, fasta_seqs, range_dict, filename):
        recs = []
        for item in fasta_seqs:
            fulldesc = item[0]
            desc = " ".join(fulldesc.split(" ")[1:])
            acc = fulldesc.split(".")[0][1::]
            acc_desc = fulldesc.split(":")[0][1::]
            seqrange = fulldesc.split(":")[1].split(" ")[0].split("-")
            fullseq = "".join(item[1::])
            for start, stop in range_dict[acc]:
                desc_range = str(int(seqrange[0]) + start) + "_" + str(int(seqrange[0]) + stop)
                acc_id = acc_desc + "_" + desc_range
                seq = fullseq[start:stop]
                rec = SeqRecord(Seq(seq), id=acc_id, description=desc)
                recs.append(rec)

        SeqIO.write(recs, filename, "fasta")

    def write_nontarget_sequences(self):
        # faster but requires more RAM
        db = self.config.customdb
        if db is None:
            db = "nt"

        dbids = os.path.join(self.primer_qc_dir, "primerBLAST_DBIDS.csv")
        df = pd.read_csv(dbids, header=None)
        df.columns = ["Accession", "Start", "Stop"]
        df.sort_values(["Accession"], inplace=True)

        seqcount = len(df.index)
        G.comm_log("Found " + str(seqcount) + " sequences for the non-target DB", newline=True)
        parts = len(df.index)//self.maxgroupsize + 1
        chunks = np.array_split(df, parts)

        for part, chunk in enumerate(chunks):
            start = chunk.groupby(["Accession"])["Start"].min()
            stop = chunk.groupby(["Accession"])["Stop"].max()
            one_extraction = pd.concat([start, stop], axis=1).reset_index().values.tolist()

            keys = list(set(chunk["Accession"]))
            range_dict = {}
            for k in keys:
                ranges = (chunk[chunk["Accession"] == k][["Start", "Stop"]].values - start[k]).tolist()
                range_dict.update({k: ranges})

            filename = "BLASTnontarget" + str(part) + ".sequences"
            filepath = os.path.join(self.primer_qc_dir, filename)
            if not os.path.isfile(filepath):
                G.comm_log("Start writing " + filename)
                G.comm_log("Start DB extraction")
                fasta_seqs = G.run_parallel(
                        P.get_seq_fromDB, one_extraction, db)
                try:
                    self.write_sequences(fasta_seqs, range_dict, filepath)
                except (KeyboardInterrupt, SystemExit):
                    G.keyexit_rollback("DB extraction", fp=filepath)
                    raise
                G.comm_log("Finished writing " + filename)
            else:
                G.comm_log("Skip writing " + filename)


BlastParser(config, "conserved").main()