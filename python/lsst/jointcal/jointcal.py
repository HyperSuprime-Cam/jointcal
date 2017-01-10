# See COPYRIGHT file at the top of the source tree.

from __future__ import division, absolute_import, print_function
from builtins import str
from builtins import range

import os
import collections

import lsst.utils
import lsst.pex.config as pexConfig
import lsst.pipe.base as pipeBase
import lsst.afw.image as afwImage
import lsst.afw.geom as afwGeom
import lsst.afw.coord as afwCoord
import lsst.pex.exceptions as pexExceptions

from lsst.meas.astrom.loadAstrometryNetObjects import LoadAstrometryNetObjectsTask
from lsst.meas.astrom import AstrometryNetDataConfig
from lsst.meas.algorithms.sourceSelector import sourceSelectorRegistry

from .dataIds import PerTractCcdDataIdContainer

from . import jointcalLib

__all__ = ["JointcalConfig", "JointcalTask"]


class JointcalRunner(pipeBase.TaskRunner):
    """Subclass of TaskRunner for jointcalTask (copied from the HSC MosaicRunner)

    jointcalTask.run() takes a number of arguments, one of which is a list of dataRefs
    extracted from the command line (whereas most CmdLineTasks' run methods take
    single dataRef, are are called repeatedly).  This class transforms the processed
    arguments generated by the ArgumentParser into the arguments expected by
    MosaicTask.run().

    See pipeBase.TaskRunner for more information, but note that the multiprocessing
    code path does not apply, because MosaicTask.canMultiprocess == False.
    """

    @staticmethod
    def getTargetList(parsedCmd, **kwargs):
        """
        Return a list of tuples per tract, each containing (dataRefs, kwargs).

        Jointcal operates on lists of dataRefs simultaneously.
        """
        kwargs['profile_jointcal'] = parsedCmd.profile_jointcal

        # organize data IDs by tract
        refListDict = {}
        for ref in parsedCmd.id.refList:
            refListDict.setdefault(ref.dataId["tract"], []).append(ref)
        # we call run() once with each tract
        result = [(refListDict[tract], kwargs) for tract in sorted(refListDict.keys())]
        return result

    def __call__(self, args):
        """
        @param args     Arguments for Task.run()

        @return
        - None if self.doReturnResults is False
        - A pipe.base.Struct containing these fields if self.doReturnResults is True:
            - dataRef: the provided data references, with update post-fit WCS's.
        """
        task = self.TaskClass(config=self.config, log=self.log)
        dataRefList, kwargs = args
        result = task.run(dataRefList, **kwargs)
        if self.doReturnResults:
            return pipeBase.Struct(result=result)


class JointcalConfig(pexConfig.Config):
    """Config for jointcalTask"""

    coaddName = pexConfig.Field(
        doc="Type of coadd, typically deep or goodSeeing",
        dtype=str,
        default="deep"
    )
    posError = pexConfig.Field(
        doc="Constant term for error on position (in pixel unit)",
        dtype=float,
        default=0.02,
    )
    polyOrder = pexConfig.Field(
        doc="Polynomial order for fitting distorsion",
        dtype=int,
        default=3,
    )
    sourceSelector = sourceSelectorRegistry.makeField(
        doc="How to select sources for cross-matching",
        default="astrometry"
    )

    def setDefaults(self):
        sourceSelector = self.sourceSelector["astrometry"]
        sourceSelector.setDefaults()
        # don't want to lose existing flags, just add to them.
        sourceSelector.badFlags.extend(["slot_Shape_flag"])
        # This should be used to set the FluxField value in jointcal::JointcalControl
        sourceSelector.sourceFluxType = 'Calib'


class JointcalTask(pipeBase.CmdLineTask):
    """Jointly astrometrically (photometrically later) calibrate a group of images."""

    ConfigClass = JointcalConfig
    RunnerClass = JointcalRunner
    _DefaultName = "jointcal"

    def __init__(self, profile_jointcal=False, **kwargs):
        """
        Instantiate a JointcalTask.

        Parameters
        ----------
        profile_jointcal : bool
            set to True to profile different stages of this jointcal run.
        """
        pipeBase.CmdLineTask.__init__(self, **kwargs)
        self.profile_jointcal = profile_jointcal
        self.makeSubtask("sourceSelector")

    # We don't need to persist config and metadata at this stage.
    # In this way, we don't need to put a specific entry in the camera mapper policy file
    def _getConfigName(self):
        return None

    def _getMetadataName(self):
        return None

    @classmethod
    def _makeArgumentParser(cls):
        """Create an argument parser"""
        parser = pipeBase.ArgumentParser(name=cls._DefaultName)
        parser.add_argument("--profile_jointcal", default=False, action="store_true",
                            help="Profile steps of jointcal separately.")
        parser.add_id_argument("--id", "calexp", help="data ID, e.g. --selectId visit=6789 ccd=0..9",
                               ContainerClass=PerTractCcdDataIdContainer)
        return parser

    def _build_ccdImage(self, dataRef, associations, jointcalControl):
        """
        Extract the necessary things from this dataRef to add a new ccdImage.

        Parameters
        ----------
        dataRef : lsst.daf.persistence.ButlerDataRef
            dataRef to extract info from.
        associations : lsst.jointcal.Associations
            object to add the info to, to construct a new CcdImage
        jointcalControl : jointcal.JointcalControl
            control object for associations management

        Returns
        ------
        afw.image.TanWcs
            the TAN WCS of this image
        """
        src = dataRef.get("src", immediate=True)
        md = dataRef.get("calexp_md", immediate=True)
        calexp = dataRef.get("calexp", immediate=True)
        visitInfo = calexp.getInfo().getVisitInfo()
        ccdname = calexp.getDetector().getId()

        tanwcs = afwImage.TanWcs.cast(afwImage.makeWcs(md))
        lLeft = afwImage.getImageXY0FromMetadata(afwImage.wcsNameForXY0, md)
        uRight = afwGeom.Point2I(lLeft.getX() + md.get("NAXIS1") - 1, lLeft.getY() + md.get("NAXIS2") - 1)
        bbox = afwGeom.Box2I(lLeft, uRight)
        calib = afwImage.Calib(md)
        filt = calexp.getInfo().getFilter().getName()

        goodSrc = self.sourceSelector.selectSources(src)

        if len(goodSrc.sourceCat) == 0:
            print("no stars selected in ", dataRef.dataId["visit"], ccdname)
            return tanwcs
        print("%d stars selected in visit %d - ccd %d" % (len(goodSrc.sourceCat),
                                                          dataRef.dataId["visit"],
                                                          ccdname))
        associations.AddImage(goodSrc.sourceCat, tanwcs, visitInfo, bbox, filt, calib,
                              dataRef.dataId['visit'], ccdname, jointcalControl)
        return tanwcs

    @pipeBase.timeMethod
    def run(self, dataRefs, profile_jointcal=False):
        """
        Jointly calibrate the astrometry and photometry across a set of images.

        Parameters
        ----------
        dataRefs : list of lsst.daf.persistence.ButlerDataRef
            List of data references to the exposures to be fit.
        profile_jointcal : bool
            Profile the individual steps of jointcal.

        Returns
        -------
        pipe.base.Struct
            struct containing:
            * dataRefs: the provided data references that were fit (with updated WCSs)
            * oldWcsList: the original WCS from each dataRef
        """
        if len(dataRefs) == 0:
            raise ValueError('Need a list of data references!')

        sourceFluxField = "slot_%sFlux" % (self.sourceSelector.config.sourceFluxType,)
        jointcalControl = jointcalLib.JointcalControl(sourceFluxField)
        associations = jointcalLib.Associations()

        load_cat_prof_file = 'jointcal_load_catalog.prof' if profile_jointcal else ''
        with pipeBase.cmdLineTask.profile(load_cat_prof_file):
            oldWcsList = [self._build_ccdImage(ref, associations, jointcalControl) for ref in dataRefs]

        matchCut = 3.0
        # TODO: this should not print "trying to invert a singular transformation:"
        # if it does that, something's not right about the WCS...
        associations.AssociateCatalogs(matchCut)

        # Use external reference catalogs handled by LSST stack mechanism
        # Get the bounding box overlapping all associated images
        # ==> This is probably a bad idea to do it this way <== To be improved
        bbox = associations.GetRaDecBBox()
        center = afwCoord.Coord(bbox.getCenter(), afwGeom.degrees)
        corner = afwCoord.Coord(bbox.getMax(), afwGeom.degrees)
        radius = center.angularSeparation(corner).asRadians()

        # Get astrometry_net_data path
        anDir = lsst.utils.getPackageDir('astrometry_net_data')
        if anDir is None:
            raise RuntimeError("astrometry_net_data is not setup")

        andConfig = AstrometryNetDataConfig()
        andConfigPath = os.path.join(anDir, "andConfig.py")
        if not os.path.exists(andConfigPath):
            raise RuntimeError("astrometry_net_data config file '%s' required but not found" % andConfigPath)
        andConfig.load(andConfigPath)

        task = LoadAstrometryNetObjectsTask.ConfigClass()
        loader = LoadAstrometryNetObjectsTask(task)

        # TODO: I don't think this is the "default" filter...
        # Determine default filter associated to the catalog
        filt, mfilt = list(andConfig.magColumnMap.items())[0]
        print("Using", filt, "band for reference flux")
        refCat = loader.loadSkyCircle(center, afwGeom.Angle(radius, afwGeom.radians), filt).refCat

        # associations.CollectRefStars(False) # To use USNO-A catalog

        associations.CollectLSSTRefStars(refCat, filt)
        associations.SelectFittedStars()
        associations.DeprojectFittedStars()  # required for AstromFit

        # TODO: these should be len(blah), but we need this properly wrapped first.
        if associations.refStarListSize() == 0:
            raise RuntimeError('No stars in the reference star list!')
        if len(associations.ccdImageList) == 0:
            raise RuntimeError('No images in the ccdImageList!')
        if associations.fittedStarListSize() == 0:
            raise RuntimeError('No stars in the fittedStarList!')

        astrometry = self._fit_astrometry(associations)
        photometry = self._fit_photometry(associations)

        # TODO: not clear that this is really needed any longer?
        # TODO: makeResTuple should at least be renamed, if we do want to keep that big data-dump around.
        # Fill reference and measurement n-tuples for each tract
        tupleName = "res_" + str(dataRefs[0].dataId["tract"]) + ".list"
        astrometry.fit.makeResTuple(tupleName)

        self._write_results(associations, astrometry.model, photometry.model, dataRefs)

        return pipeBase.Struct(dataRefs=dataRefs, oldWcsList=oldWcsList)

    def _fit_photometry(self, associations):
        """
        Fit the photometric data.

        Parameters
        ----------
        associations : lsst.jointcal.Associations
            The star/reference star associations to fit.

        Returns
        -------
        namedtuple
            fit : lsst.jointcal.PhotomFit
                The photometric fitter used to perform the fit.
            model : lsst.jointcal.PhotomModel
                The photometric model that was fit.
        """

        print("====== Starting photometric fitting")
        model = jointcalLib.SimplePhotomModel(associations.getCcdImageList())

        fit = jointcalLib.PhotomFit(associations, model, self.config.posError)
        fit.minimize("Model")
        chi2 = fit.computeChi2()
        print(chi2)
        fit.minimize("Fluxes")
        chi2 = fit.computeChi2()
        print(chi2)
        fit.minimize("Model Fluxes")
        chi2 = fit.computeChi2()
        print(chi2)

        Photometry = collections.namedtuple('Photometry', ('fit', 'model'))
        return Photometry(fit, model)

    def _fit_astrometry(self, associations):
        """
        Fit the astrometric data.

        Parameters
        ----------
        associations : lsst.jointcal.Associations
            The star/reference star associations to fit.

        Returns
        -------
        namedtuple
            fit : lsst.jointcal.AstromFit
                The astrometric fitter used to perform the fit.
            model : lsst.jointcal.AstromModel
                The astrometric model that was fit.
            sky_to_tan_projection : lsst.jointcal.ProjectionHandler
                The model for the sky to tangent plane projection that was used in the fit.
        """

        print("====== Starting astrometric fitting")
        # NOTE: need to return sky_to_tan_projection so that it doesn't get garbage collected.
        # TODO: could we package sky_to_tan_projection and model together so we don't have to manage
        # them so carefully?
        sky_to_tan_projection = jointcalLib.OneTPPerVisitHandler(associations.getCcdImageList())
        model = jointcalLib.SimplePolyModel(associations.getCcdImageList(), sky_to_tan_projection,
                                            True, 0, self.config.polyOrder)

        fit = jointcalLib.AstromFit(associations, model, self.config.posError)
        fit.minimize("Distortions")
        chi2 = fit.computeChi2()
        print(chi2)
        fit.minimize("Positions")
        chi2 = fit.computeChi2()
        print(chi2)
        fit.minimize("Distortions Positions")
        chi2 = fit.computeChi2()
        print(chi2)

        for i in range(20):
            r = fit.minimize("Distortions Positions", 5)  # outliers removal at 5 sigma.
            chi2 = fit.computeChi2()
            print(chi2)
            if r == 0:
                print("""fit has converged - no more outliers - redo minimixation\
                      one more time in case we have lost accuracy in rank update""")
                # Redo minimization one more time in case we have lost accuracy in rank update
                r = fit.minimize("Distortions Positions", 5)  # outliers removal at 5 sigma.
                chi2 = fit.computeChi2()
                print(chi2)
                break
            elif r == 2:
                print("minimization failed")
            elif r == 1:
                print("still some ouliers but chi2 increases - retry")
            else:
                break
                print("unxepected return code from minimize")

        Astrometry = collections.namedtuple('Astrometry', ('fit', 'model', 'sky_to_tan_projection'))
        return Astrometry(fit, model, sky_to_tan_projection)

    def _write_results(self, associations, astrom_model, photom_model, dataRefs):
        """
        Write the fitted results (photometric and astrometric) to a new 'wcs' dataRef.

        Parameters
        ----------
        associations : lsst.jointcal.Associations
            The star/reference star associations to fit.
        astrom_model : lsst.jointcal.AstromModel
            The astrometric model that was fit.
        photom_model : lsst.jointcal.PhotomModel
            The photometric model that was fit.
        dataRefs : list of lsst.daf.persistence.ButlerDataRef
            List of data references to the exposures that were fit.
        """

        ccdImageList = associations.getCcdImageList()
        for ccdImage in ccdImageList:
            tanSip = astrom_model.ProduceSipWcs(ccdImage)
            frame = ccdImage.ImageFrame()
            tanWcs = afwImage.TanWcs.cast(jointcalLib.GtransfoToTanWcs(tanSip, frame, False))

            # TODO: there must be a better way to identify this ccdImage?
            name = ccdImage.Name()
            visit, ccd = name.split('_')
            for dataRef in dataRefs:
                calexp = dataRef.get("calexp")
                ccdname = calexp.getDetector().getId()
                if dataRef.dataId["visit"] == int(visit) and ccdname == int(ccd):
                    print("Updating WCS for visit: %d, ccd%d" % (int(visit), int(ccd)))
                    exp = afwImage.ExposureI(0, 0, tanWcs)
                    exp.setCalib(calexp.getCalib())  # start with the original calib
                    fluxMag0, fluxMag0Sigma = calexp.getCalib().getFluxMag0()
                    exp.getCalib().setFluxMag0(fluxMag0*photom_model.photomFactor(ccdImage), fluxMag0Sigma)
                    try:
                        dataRef.put(exp, 'wcs')
                    except pexExceptions.Exception as e:
                        self.log.warn('Failed to write updated Wcs: ' + str(e))
                    break
