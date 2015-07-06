#include <algorithm>

#include "Eigen/Core"
#include "lsst/meas/simastrom/Gtransfo.h"
#include "lsst/afw/image/ImageUtils.h"
//#include "lsst/afw/geom/Point.h"
#include "lsst/meas/simastrom/Point.h"
#include "lsst/afw/image/TanWcs.h"
#include "lsst/daf/base/PropertySet.h"

namespace simAstrom = lsst::meas::simastrom; 

static const int lsstToFitsPixels = +1;
static const int fitsToLsstPixels = -1;

typedef boost::shared_ptr<simAstrom::GtransfoPoly> GtPoly_Ptr;
	

simAstrom::TanSipPix2RaDec ConvertTanWcs(const lsst::afw::image::TanWcs* wcs)
{
  //std::unique_ptr<simAstrom::GtransfoPoly> sipCorr(0);
  GtPoly_Ptr sipCorr(new simAstrom::GtransfoPoly(0));

  /* TanWcs::pixelToSkyImpl adds  - PixelZeroPos + lsstToFitsPixels
     to the input coordinates. */

  simAstrom::GtransfoLinShift firstShift(-lsst::afw::image::PixelZeroPos + lsstToFitsPixels,
					 -lsst::afw::image::PixelZeroPos + lsstToFitsPixels);

  /* beware : Wccs::getPixelOrigin return crpix+ fitsToLsstPixels */
  lsst::afw::geom::Point2D offset_crpix = wcs->getPixelOrigin();

  lsst::daf::base::PropertyList::Ptr wcsMeta = wcs->getFitsMetadata();

  if (wcs->hasDistortion())
    {
      Eigen::MatrixXd sipA;
      Eigen::MatrixXd sipB;
      lsst::afw::image::TanWcs::decodeSipHeader(*wcsMeta, "A", sipA);
      lsst::afw::image::TanWcs::decodeSipHeader(*wcsMeta, "B", sipB);
  
      int sipOrder = std::max(wcsMeta->get<int>("A_ORDER"), wcsMeta->get<int>("B_ORDER"));

      simAstrom::GtransfoPoly sipPoly(sipOrder);
      for (int i=0; i<=sipOrder; ++i)
        {
	  for (int j=0; j<=sipOrder; ++j)
	    {
	      if (i<sipA.cols() && j<sipA.rows()) 
	        sipPoly.Coeff(i,j,0) = sipA(i,j);
	      if (i<sipB.cols() && j<sipB.rows()) 
	        sipPoly.Coeff(i,j,1) = sipB(i,j);
	    }
	}

      /*
      TanWcs::undistorPixel adds (- wcs_info->crpix) (line 330)  to the coordinates
	 before computing the polynomials so the total shift reads:

	 -PixelZeroPos + lsstToFitsPixels -(offset_crpix-fitsToLsstPixels)
	 = -PixelZeroPos -offset_crpix
      */

      simAstrom::GtransfoLinShift secondShift(-offset_crpix[0]+fitsToLsstPixels,
					      -offset_crpix[1]+fitsToLsstPixels);

      /* then the SIP correction (TanWcs::undistorPixel, last line)
	 returns pix + sipPoly*secondShift(pix) where pix =
	 firstShift(input) */

      /* requires operator + for GtransfoPoly : */
	
      simAstrom::GtransfoPoly actualSip = firstShift+sipPoly*secondShift*firstShift;
      	
      sipCorr.reset(new simAstrom::GtransfoPoly(actualSip));
    }

  // now compute the lin part (nothing to do with SIP) */
  Eigen::Matrix2d cdMat = wcs->getCDMatrix();
  simAstrom::GtransfoLin cdTrans;
  cdTrans.Coeff(1,0,0) = cdMat(0,0); // CD1_1
  cdTrans.Coeff(0,1,0) = cdMat(0,1); // CD1_2 
  cdTrans.Coeff(1,0,1) = cdMat(1,0); // CD2_1
  cdTrans.Coeff(0,1,1) = cdMat(1,1); // CD2_1
  simAstrom::GtransfoLinShift crpixShift(offset_crpix[0] -  fitsToLsstPixels,
					 offset_crpix[1] -  fitsToLsstPixels); 

  // CD's apply to CRPIX-shifted coordinate
  simAstrom::GtransfoLin linPart = cdTrans * crpixShift;

  if (!wcs->hasDistortion()) // have to apply firstShift
    linPart = linPart* firstShift;

  // tangent point : no idea if this works....
  lsst::afw::coord::Coord tp = wcs->getSkyOrigin()->getPosition(lsst::afw::geom::degrees);

//  lsst::afw::geom::Point tangentPoint(tp[0], tp[1]);
  lsst::meas::simastrom::Point tangentPoint(tp[0], tp[1]);

  // return simAstrom::TanSipPix2RaDec(linPart, tangentPoint, sipCorr->get());
  return simAstrom::TanSipPix2RaDec(linPart, tangentPoint, (const simAstrom::GtransfoPoly*) sipCorr.get());
}

  
   



  
