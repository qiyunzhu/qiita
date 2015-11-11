# -----------------------------------------------------------------------------
# Copyright (c) 2014--, The Qiita Development Team.
#
# Distributed under the terms of the BSD 3-clause License.
#
# The full license is in the file LICENSE, distributed with this software.
# -----------------------------------------------------------------------------

from __future__ import division
from future.utils import viewitems
from datetime import datetime

from .base import QiitaObject
from .sql_connection import TRN
from .exceptions import (QiitaDBArtifactCreationError,
                         QiitaDBArtifactDeletionError,
                         QiitaDBOperationNotPermittedError)
from .util import (convert_to_id, insert_filepaths,
                   move_filepaths_to_upload_folder, retrieve_filepaths)
from .software import Parameters, Command
from .study import Study
from .metadata_template import PrepTemplate


class Artifact(QiitaObject):
    r"""Any kind of file (or group of files) stored in the system and its
    attributes

    Attributes
    ----------
    timestamp
    processing_parameters
    visibility
    artifact_type
    data_type
    can_be_submitted_to_ebi
    can_be_submitted_to_vamps
    is_submitted_to_vamps
    filepaths
    parents
    prep_template
    ebi_run_accession
    study

    Methods
    -------
    create
    delete

    See Also
    --------
    qiita_db.QiitaObject
    """
    _table = "artifact"

    @classmethod
    def create(cls, filepaths, artifact_type, prep_template=None,
               parents=None, processing_parameters=None,
               can_be_submitted_to_ebi=False, can_be_submitted_to_vamps=False):
        r"""Creates a new artifact in the system

        The parameters depend on how the artifact was generated:
            - If the artifact was uploaded by the user, the parameter
            `prep_template` should be provided and the parameters `parents` and
            `processing_parameters` should not be provided.
            - If the artifact was generated by processing one or more
            artifacts, the parameters `parents` and `processing_parameters`
            should be provided and the parameter `prep_template` should not
            be provided.

        The parameters `can_be_submitted_to_ebi` and
        `can_be_submitted_to_vamps` defaults to false and they should be
        provided if and only if the artifact can be submitted to EBI and
        VAMPS, respectively.

        Parameters
        ----------
        filepaths : iterable of tuples (str, int)
            A list of 2-tuples in which the first element is the artifact
            file path and the second one is the file path type id
        artifact_type : str
            The type of the artifact
        prep_template : qiita_db.metadata_template.PrepTemplate, optional
            If the artifact is being uploaded by the user, the prep template
            to which the artifact should be linked to. If not provided,
            `parents` should be provided.
        parents : iterable of qiita_db.artifact.Artifact, optional
            The list of artifacts from which the new artifact has been
            generated. If not provided, `prep_template` should be provided.
        processing_parameters : qiita_db.software.Parameter, optional
            The processing parameters used to generate the new artifact
            from `parents`. It is required if `parents` is provided. It should
            not be provided if `prep_template` is provided.
        can_be_submitted_to_ebi : bool, optional
            Whether the new artifact can be submitted to EBI or not. Default:
            `False`.
        can_be_submitted_to_vamps : bool, optional
            Whether the new artifact can be submitted to VAMPS or not. Default:
            `False`.

        Returns
        -------
        qiita_db.artifact.Artifact
            A new instance of Artifact

        Raises
        ------
        QiitaDBArtifactCreationError
            If `filepaths` is not provided
            If both `parents` and `prep_template` are provided
            If none of `parents` and `prep_template` are provided
            If `parents` is provided but `processing_parameters` is not
            If both `prep_template` and `processing_parameters` is provided
            If not all the artifacts in `parents` belong to the same study

        Notes
        -----
        The visibility of the artifact is set by default to `sandbox`
        The timestamp of the artifact is set by default to `datetime.now()`
        """
        # We need at least one file
        if not filepaths:
            raise QiitaDBArtifactCreationError(
                "at least one filepath is required.")

        # Parents or prep template must be provided, but not both
        if parents and prep_template:
            raise QiitaDBArtifactCreationError(
                "parents or prep_template should be provided but not both")
        elif not (parents or prep_template):
            raise QiitaDBArtifactCreationError(
                "at least parents or prep_template must be provided")
        elif parents and not processing_parameters:
            # If parents is provided, processing parameters should also be
            # provided
            raise QiitaDBArtifactCreationError(
                "if parents is provided, processing_parameters should also be"
                "provided.")
        elif prep_template and processing_parameters:
            # If prep_template is provided, processing_parameters should not be
            # provided
            raise QiitaDBArtifactCreationError(
                "if prep_template is provided, processing_parameters should "
                "not be provided.")

        timestamp = datetime.now()

        with TRN:
            visibility_id = convert_to_id("sandbox", "visibility")
            artifact_type_id = convert_to_id(artifact_type, "artifact_type")

            if parents:
                # Check that all parents belong to the same study
                studies = {p.study.id for p in parents}
                if len(studies) > 1:
                    raise QiitaDBArtifactCreationError(
                        "parents from multiple studies provided: %s"
                        % ', '.join(studies))
                study_id = studies.pop()

                # Check that all parents have the same data type
                dtypes = {p.data_type for p in parents}
                if len(dtypes) > 1:
                    raise QiitaDBArtifactCreationError(
                        "parents have multiple data types: %s"
                        % ", ".join(dtypes))
                dtype_id = convert_to_id(dtypes.pop(), "data_type")

                # Create the artifact
                sql = """INSERT INTO qiita.artifact
                            (generated_timestamp, command_id, data_type_id,
                             command_parameters_id, visibility_id,
                             artifact_type_id, can_be_submitted_to_ebi,
                             can_be_submitted_to_vamps, submitted_to_vamps)
                         VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                         RETURNING artifact_id"""
                sql_args = [timestamp, processing_parameters.command.id,
                            dtype_id, processing_parameters.id, visibility_id,
                            artifact_type_id, can_be_submitted_to_ebi,
                            can_be_submitted_to_vamps, False]
                TRN.add(sql, sql_args)
                a_id = TRN.execute_fetchlast()

                # Associate the artifact with its parents
                sql = """INSERT INTO qiita.parent_artifact
                            (artifact_id, parent_id)
                         VALUES (%s, %s)"""
                sql_args = [(a_id, p.id) for p in parents]
                TRN.add(sql, sql_args, many=True)

                instance = cls(a_id)
            else:
                dtype_id = convert_to_id(prep_template.data_type(),
                                         "data_type")
                # Create the artifact
                sql = """INSERT INTO qiita.artifact
                            (generated_timestamp, visibility_id,
                             artifact_type_id, data_type_id,
                             can_be_submitted_to_ebi,
                             can_be_submitted_to_vamps, submitted_to_vamps)
                         VALUES (%s, %s, %s, %s, %s, %s, %s)
                         RETURNING artifact_id"""
                sql_args = [timestamp, visibility_id, artifact_type_id,
                            dtype_id, can_be_submitted_to_ebi,
                            can_be_submitted_to_vamps, False]
                TRN.add(sql, sql_args)
                a_id = TRN.execute_fetchlast()

                # Associate the artifact with the prep template
                instance = cls(a_id)
                prep_template.artifact = instance
                study_id = prep_template.study_id

            # Associate the artifact with the study
            sql = """INSERT INTO qiita.study_artifact (study_id, artifact_id)
                     VALUES (%s, %s)"""
            sql_args = [study_id, a_id]
            TRN.add(sql, sql_args)

            # Associate the artifact with its filepaths
            fp_ids = insert_filepaths(filepaths, a_id, artifact_type,
                                      "filepath")
            sql = """INSERT INTO qiita.artifact_filepath
                        (artifact_id, filepath_id)
                     VALUES (%s, %s)"""
            sql_args = [[a_id, fp_id] for fp_id in fp_ids]
            TRN.add(sql, sql_args, many=True)
            TRN.execute()

        return instance

    @classmethod
    def delete(cls, artifact_id):
        r"""Deletes an artifact from the system

        Parameters
        ----------
        artifact_id : int
            The artifact to be removed

        Raises
        ------
        QiitaDBArtifactDeletionError
            If the artifact is public
            If the artifact has children
            If the artifact has been analyzed
            If the artifact has been submitted to EBI
            If the artifact has been submitted to VAMPS
        """
        with TRN:
            # This will fail if the artifact with id=artifact_id doesn't exist
            instance = cls(artifact_id)

            # Check if the artifact is public
            if instance.visibility == 'public':
                raise QiitaDBArtifactDeletionError(artifact_id, "it is public")

            # Check if this artifact has any children
            if instance.children:
                raise QiitaDBArtifactDeletionError(
                    artifact_id,
                    "it has children: %s"
                    % ', '.join([str(c.id) for c in instance.children]))

            # Check if the artifact has been analyzed
            sql = """SELECT EXISTS(SELECT *
                                   FROM qiita.analysis_sample
                                   WHERE artifact_id = %s)"""
            TRN.add(sql, [artifact_id])
            if TRN.execute_fetchlast():
                raise QiitaDBArtifactDeletionError(
                    artifact_id, "it has been analyzed")

            # Check if the artifact has been submitted to EBI
            if instance.can_be_submitted_to_ebi and \
                    instance.ebi_run_accessions:
                raise QiitaDBArtifactDeletionError(
                    artifact_id, "it has been submitted to EBI")

            # Check if the artifact has been submitted to VAMPS
            if instance.can_be_submitted_to_vamps and \
                    instance.is_submitted_to_vamps:
                raise QiitaDBArtifactDeletionError(
                    artifact_id, "it has been submitted to VAMPS")

            # We can now remove the artifact
            filepaths = instance.filepaths
            study = instance.study

            sql = """DELETE FROM qiita.artifact_filepath
                     WHERE artifact_id = %s"""
            TRN.add(sql, [artifact_id])

            # If the artifact doesn't have parents, we move the files to the
            # uploads folder. We also need to nullify the column in the prep
            # template table
            if not instance.parents:
                move_filepaths_to_upload_folder(study.id, filepaths)

                sql = """UPDATE qiita.prep_template
                         SET artifact_id = NULL
                         WHERE prep_template_id IN %s"""
                TRN.add(sql, [tuple(pt.id for pt in instance.prep_templates)])
            else:
                sql = """DELETE FROM qiita.parent_artifact
                         WHERE artifact_id = %s"""
                TRN.add(sql, [artifact_id])

            # Detach the artifact from the study_artifact table
            sql = "DELETE FROM qiita.study_artifact WHERE artifact_id = %s"
            TRN.add(sql, [artifact_id])

            # Delete the row in the artifact table
            sql = "DELETE FROM qiita.artifact WHERE artifact_id = %s"
            TRN.add(sql, [artifact_id])

    @property
    def timestamp(self):
        """The timestamp when the artifact was generated

        Returns
        -------
        datetime
            The timestamp when the artifact was generated
        """
        with TRN:
            sql = """SELECT generated_timestamp
                     FROM qiita.artifact
                     WHERE artifact_id = %s"""
            TRN.add(sql, [self.id])
            return TRN.execute_fetchlast()

    @property
    def processing_parameters(self):
        """The processing parameters used to generate the artifact

        Returns
        -------
        qiita_db.software.Parameters or None
            The parameters used to generate the artifact if it has parents.
            None otherwise.
        """
        with TRN:
            sql = """SELECT command_id, command_parameters_id
                     FROM qiita.artifact
                     WHERE artifact_id = %s"""
            TRN.add(sql, [self.id])
            # Only one row will be returned
            res = TRN.execute_fetchindex()[0]
            if res[0] is None:
                return None
            return Parameters(res[1], Command(res[0]))

    @property
    def visibility(self):
        """The visibility of the artifact

        Returns
        -------
        str
            The visibility of the artifact
        """
        with TRN:
            sql = """SELECT visibility
                     FROM qiita.artifact
                        JOIN qiita.visibility USING (visibility_id)
                     WHERE artifact_id = %s"""
            TRN.add(sql, [self.id])
            return TRN.execute_fetchlast()

    @visibility.setter
    def visibility(self, value):
        """Sets the visibility of the artifact

        Parameters
        ----------
        value : str
            The new visibility of the artifact
        """
        with TRN:
            sql = """UPDATE qiita.artifact
                     SET visibility_id = %s
                     WHERE artifact_id = %s"""
            TRN.add(sql, [convert_to_id(value, "visibility"), self.id])
            TRN.execute()

    @property
    def artifact_type(self):
        """The artifact type

        Returns
        -------
        str
            The artifact type
        """
        with TRN:
            sql = """SELECT artifact_type
                     FROM qiita.artifact
                        JOIN qiita.artifact_type USING (artifact_type_id)
                     WHERE artifact_id = %s"""
            TRN.add(sql, [self.id])
            return TRN.execute_fetchlast()

    @property
    def data_type(self):
        """The data type of the artifact

        Returns
        -------
        str
            The artifact data type
        """
        with TRN:
            sql = """SELECT data_type
                     FROM qiita.artifact
                        JOIN qiita.data_type USING (data_type_id)
                     WHERE artifact_id = %s"""
            TRN.add(sql, [self.id])
            return TRN.execute_fetchlast()

    @property
    def can_be_submitted_to_ebi(self):
        """Whether the artifact can be submitted to EBI or not

        Returns
        -------
        bool
            True if the artifact can be submitted to EBI. False otherwise.
        """
        with TRN:
            sql = """SELECT can_be_submitted_to_ebi
                     FROM qiita.artifact
                     WHERE artifact_id = %s"""
            TRN.add(sql, [self.id])
            return TRN.execute_fetchlast()

    @property
    def ebi_run_accessions(self):
        """The EBI run accessions attached to this artifact

        Returns
        -------
        dict of {str: str}
            The EBI run accessions keyed by sample id

        Raises
        ------
        QiitaDBOperationNotPermittedError
            If the artifact cannot be submitted to EBI
        """
        with TRN:
            if not self.can_be_submitted_to_ebi:
                raise QiitaDBOperationNotPermittedError(
                    "Artifact %s cannot be submitted to EBI" % self.id)
            sql = """SELECT sample_id, ebi_run_accession
                     FROM qiita.ebi_run_accession
                     WHERE artifact_id = %s"""
            TRN.add(sql, [self.id])
            return {s_id: ebi_acc for s_id, ebi_acc in
                    TRN.execute_fetchindex()}

    @ebi_run_accessions.setter
    def ebi_run_accessions(self, values):
        """Set the EBI run accession attached to this artifact

        Parameters
        ----------
        values : dict of {str: str}
            The EBI accession number keyed by sample id

        Raises
        ------
        QiitaDBOperationNotPermittedError
            If the artifact cannot be submitted to EBI
            If the artifact has been already submitted to EBI
        """
        with TRN:
            if not self.can_be_submitted_to_ebi:
                raise QiitaDBOperationNotPermittedError(
                    "Artifact %s cannot be submitted to EBI" % self.id)

            sql = """SELECT EXISTS(SELECT *
                                   FROM qiita.ebi_run_accession
                                   WHERE artifact_id = %s)"""
            TRN.add(sql, [self.id])
            if TRN.execute_fetchlast():
                raise QiitaDBOperationNotPermittedError(
                    "Artifact %s already submitted to EBI" % self.id)

            sql = """INSERT INTO qiita.ebi_run_accession
                        (sample_id, artifact_id, ebi_run_accession)
                     VALUES (%s, %s, %s)"""
            sql_args = [[sample, self.id, accession]
                        for sample, accession in viewitems(values)]
            TRN.add(sql, sql_args, many=True)
            TRN.execute()

    @property
    def can_be_submitted_to_vamps(self):
        """Whether the artifact can be submitted to VAMPS or not

        Returns
        -------
        bool
            True if the artifact can be submitted to VAMPS. False otherwise.
        """
        with TRN:
            sql = """SELECT can_be_submitted_to_vamps
                     FROM qiita.artifact
                     WHERE artifact_id = %s"""
            TRN.add(sql, [self.id])
            return TRN.execute_fetchlast()

    @property
    def is_submitted_to_vamps(self):
        """Whether if the artifact has been submitted to VAMPS or not

        Returns
        -------
        bool
            True if the artifact has been submitted to VAMPS. False otherwise

        Raises
        ------
        QiitaDBOperationNotPermittedError
            If the artifact cannot be submitted to VAMPS
        """
        with TRN:
            if not self.can_be_submitted_to_vamps:
                raise QiitaDBOperationNotPermittedError(
                    "Artifact %s cannot be submitted to VAMPS" % self.id)
            sql = """SELECT submitted_to_vamps
                     FROM qiita.artifact
                     WHERE artifact_id = %s"""
            TRN.add(sql, [self.id])
            return TRN.execute_fetchlast()

    @is_submitted_to_vamps.setter
    def is_submitted_to_vamps(self, value):
        """Set if the artifact has been submitted to VAMPS

        Parameters
        ----------
        value : bool
            Whether the artifact has been submitted to VAMPS or not

        Raises
        ------
        QiitaDBOperationNotPermittedError
            If the artifact cannot be submitted to VAMPS
        """
        with TRN:
            if not self.can_be_submitted_to_vamps:
                raise QiitaDBOperationNotPermittedError(
                    "Artifact %s cannot be submitted to VAMPS" % self.id)
            sql = """UPDATE qiita.artifact
                     SET submitted_to_vamps = %s
                     WHERE artifact_id = %s"""
            TRN.add(sql, [value, self.id])
            TRN.execute()

    @property
    def filepaths(self):
        """Returns the filepaths associated with the artifact

        Returns
        -------
        list of (int, str, str)
            A list of (filepath_id, path, filetype) of all the files associated
            with the artifact
        """
        return retrieve_filepaths("artifact_filepath", "artifact_id", self.id)

    @property
    def parents(self):
        """Returns the parents of the artifact

        Returns
        -------
        list of qiita_db.artifact.Artifact
            The parent artifacts
        """
        with TRN:
            sql = """SELECT parent_id
                     FROM qiita.parent_artifact
                     WHERE artifact_id = %s"""
            TRN.add(sql, [self.id])
            return [Artifact(p_id) for p_id in TRN.execute_fetchflatten()]

    @property
    def children(self):
        """Returns the list of children of the artifact

        Returns
        -------
        list of qiita_db.artifact.Artifact
            The children artifacts
        """
        with TRN:
            sql = """SELECT artifact_id
                     FROM qiita.parent_artifact
                     WHERE parent_id = %s"""
            TRN.add(sql, [self.id])
            return [Artifact(c_id) for c_id in TRN.execute_fetchflatten()]

    @property
    def prep_templates(self):
        """The prep templates attached to this artifact

        Returns
        -------
        list of qiita_db.metadata_template.PrepTemplate
        """
        with TRN:
            sql = """SELECT prep_template_id
                     FROM qiita.prep_template
                     WHERE artifact_id IN (
                        SELECT *
                        FROM qiita.find_artifact_roots(%s))"""
            TRN.add(sql, [self.id])
            return [PrepTemplate(pt_id)
                    for pt_id in TRN.execute_fetchflatten()]

    @property
    def study(self):
        """The study to which the artifact belongs to

        Returns
        -------
        qiita_db.study.Study
            The study that owns the artifact
        """
        with TRN:
            sql = """SELECT study_id
                     FROM qiita.study_artifact
                     WHERE artifact_id = %s"""
            TRN.add(sql, [self.id])
            return Study(TRN.execute_fetchlast())
