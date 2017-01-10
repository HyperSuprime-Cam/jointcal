#ifndef PHOTOMFIT__H
#define PHOTOMFIT__H

#include <string>
#include <iostream>
#include <sstream>
#include <map>

#include "lsst/jointcal/CcdImage.h"
#include "lsst/jointcal/Eigenstuff.h"
#include "lsst/jointcal/Tripletlist.h"
#include "lsst/jointcal/PhotomModel.h"
#include "lsst/jointcal/Chi2.h"

namespace lsst {
namespace jointcal {

class Associations;

//! Class that handles the photometric least squares problem.
class PhotomFit {
  private :

  Associations &_associations;
  std::string _whatToFit;
  bool _fittingModel, _fittingFluxes;
  unsigned _nParModel, _nParFluxes, _nParTot;
  PhotomModel * _photomModel;
  double _fluxError;
  int _lastNTrip; // last triplet count, used to speed up allocation

 public :

  //! this is the only constructor
  PhotomFit (Associations &associations, PhotomModel *model, double fluxError);

  /**
   * Does a 1 step minimization, assuming a linear model.
   *
   * It calls assignIndices, LSDerivatives, solves the linear system and calls
   * offsetParams. No line search. Relies on sparse linear algebra.
   *
   * This is a complete Newton Raphson step. Compute first and second
   * derivatives, solve for the step and apply it, without a line search.
   *
   * @param[in]  whatToFit  Valid strings : "Model", "Fluxes", which define
   *                        which parameter sets are going to be fitted.
   *                        whatToFit="Model Fluxes"  will set both parameter
   *                        sets variable when computing derivatives. Provided
   *                        it contains "Model", whatToFit is passed over to the
   *                        PhotomModel, and can hence be used to control more
   *                        finely which subsets of the photometric model are
   *                        being fitted, if the the actual PhotomModel
   *                        implements such a possibility.
   *
   * @return     false if factorization failed, true otherwise.
   */
  bool minimize(const std::string &whatToFit);

  //! Derivatives of the Chi2
  void LSDerivatives(TripletList &tripletList, Eigen::VectorXd &rhs) const;

  //! Compute the derivatives for this CcdImage. The last argument allows to to
  //! process a sub-list (used for outlier removal)
  void LSDerivatives(const CcdImage &ccdImage,
                     TripletList &tripletList, Eigen::VectorXd &rhs,
                     const MeasuredStarList *measuredStarList=nullptr) const;

  /**
   * Set parameter groups fixed or variable and assign indices to each parameter
   * in the big matrix (which will be used by OffsetParams(...).
   *
   * @param[in]  whatToFit  Valid strings : "Model", "Fluxes", which define
   *                        which parameter sets are going to be fitted.
   *                        whatToFit="Model Fluxes"  will set both parameter
   *                        sets variable when computing derivatives. Provided
   *                        it contains "Model", whatToFit is passed over to the
   *                        PhotomModel, and can hence be used to control more
   *                        finely which subsets of the photometric model are
   *                        being fitted, if the the actual PhotomModel
   *                        implements such a possibility.
   */
  void assignIndices(const std::string &whatToFit);

  /**
   * Offset the parameters by the requested quantities. The used parameter
   * layout is the one from the last call to assignIndices or minimize(). There
   * is no easy way to check that the current setting of WhatToFit and the
   * provided Delta vector are compatible. We can only test the size.
   *
   * @param[in]  delta  vector of offsets to apply
   */
  void offsetParams(const Eigen::VectorXd &delta);

  /**
   * Returns a chi2 for the current state
   */
  Chi2 computeChi2() const;

  //! Produces an ntuple
  void makeResTuple(const std::string &tupleName) const;

 private:

  template <class ListType, class Accum>
    void accumulateStat(ListType &listType, Accum &accum) const;


  void outliersContributions(MeasuredStarList &outliers,
                             TripletList &tripletList,
                             Eigen::VectorXd &grad);

  void findOutliers(double NSigCut,
                    MeasuredStarList &outliers) const;


  void getMeasuredStarIndices(const MeasuredStar &measuredStar,
                              std::vector<unsigned> &indices) const;


#ifdef STORAGE
  //! Compute the derivatives of the reference terms
  void LSDerivatives2(TripletList &tripletList, Eigen::VectorXd &rhs) const;

  //! Evaluates the chI^2 derivatives (Jacobian and gradient) for the current WhatToFit setting.


  //! returns how many outliers were removed. No refit done.
  unsigned removeOutliers(double nSigCut);

  //! Produces a tuple containing residuals of measurement terms.
  void makeMeasResTuple(const std::string &tupleName) const;

  //! Produces a tuple containing residuals of reference terms.
  void makeRefResTuple(const std::string &tupleName) const;

 private :

  Point transformFittedStar(const FittedStar &fittedStar,
                            const Gtransfo * Sky2TP,
                            const Point &refractionVector,
                            double refractionCoeff,
                            double mjd) const;

  //! only for outlier removal
  void getMeasuredStarIndices(const MeasuredStar &measuredStar,
                              std::vector<unsigned> &indices) const;
#endif
};


}} // end of namespaces
#endif /* PHOTOMFIT__H */
