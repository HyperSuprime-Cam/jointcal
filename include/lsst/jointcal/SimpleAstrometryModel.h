// -*- LSST-C++ -*-
/*
 * This file is part of jointcal.
 *
 * Developed for the LSST Data Management System.
 * This product includes software developed by the LSST Project
 * (https://www.lsst.org).
 * See the COPYRIGHT file at the top-level directory of this distribution
 * for details of code ownership.
 *
 * This program is free software: you can redistribute it and/or modify
 * it under the terms of the GNU General Public License as published by
 * the Free Software Foundation, either version 3 of the License, or
 * (at your option) any later version.
 *
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 * GNU General Public License for more details.
 *
 * You should have received a copy of the GNU General Public License
 * along with this program.  If not, see <https://www.gnu.org/licenses/>.
 */

#ifndef LSST_JOINTCAL_SIMPLE_ASTROMETRY_MODEL_H
#define LSST_JOINTCAL_SIMPLE_ASTROMETRY_MODEL_H

#include "memory"

#include "lsst/jointcal/Eigenstuff.h"

#include "lsst/jointcal/AstrometryModel.h"
#include "lsst/jointcal/AstrometryTransform.h"
#include "lsst/jointcal/SimpleAstrometryMapping.h"
#include "lsst/jointcal/ProjectionHandler.h"
#include <map>

namespace lsst {
namespace jointcal {

class CcdImage;

/* We deal here with coordinate transforms which are fitted
   and/or necessary to AstrometryFit. The classes SimpleAstrometryModel
and SimplePolyMapping implement a model where  there is one
separate transfrom per CcdImage. One could chose other setups.

*/

//! this is the model used to fit independent CCDs, meaning that there is no instrument model.
/* This modeling of distortions can even accommodate images set mixing instruments */
class SimpleAstrometryModel : public AstrometryModel {
public:
    //! Sky2TP is just a name, it can be anything
    SimpleAstrometryModel(CcdImageList const &ccdImageList,
                          const std::shared_ptr<ProjectionHandler const> projectionHandler, bool initFromWCS,
                          unsigned nNotFit = 0, unsigned order = 3);

    /// No copy or move: there is only ever one instance of a given model (i.e.. per ccd+visit)
    SimpleAstrometryModel(SimpleAstrometryModel const &) = delete;
    SimpleAstrometryModel(SimpleAstrometryModel &&) = delete;
    SimpleAstrometryModel &operator=(SimpleAstrometryModel const &) = delete;
    SimpleAstrometryModel &operator=(SimpleAstrometryModel &&) = delete;

    // The following routines are the interface to AstrometryFit
    //!
    const AstrometryMapping *getMapping(CcdImage const &) const override;

    //! Positions the various parameter sets into the parameter vector, starting at firstIndex
    Eigen::Index assignIndices(std::string const &whatToFit, Eigen::Index firstIndex) override;

    // dispaches the offsets after a fit step into the actual locations of parameters
    void offsetParams(Eigen::VectorXd const &delta) override;

    /*! the mapping of sky coordinates (i.e. the coordinate system
    in which fitted stars are reported) onto the Tangent plane
    (into which the pixel coordinates are transformed) */
    const std::shared_ptr<AstrometryTransform const> getSkyToTangentPlane(
            CcdImage const &ccdImage) const override {
        return _skyToTangentPlane->getSkyToTangentPlane(ccdImage);
    }

    //!
    void freezeErrorTransform() override;

    /// @copydoc AstrometryModel::getTotalParameters
    std::size_t getTotalParameters() const override;

    //! Access to mappings
    AstrometryTransform const &getTransform(CcdImage const &ccdImage) const;

    /// @copydoc AstrometryModel::makeSkyWcs
    std::shared_ptr<afw::geom::SkyWcs> makeSkyWcs(CcdImage const &ccdImage) const override;

    ~SimpleAstrometryModel(){};

private:
    std::unordered_map<CcdImageKey, std::unique_ptr<SimpleAstrometryMapping>> _myMap;
    const std::shared_ptr<ProjectionHandler const> _skyToTangentPlane;

    /// @copydoc AstrometryModel::findMapping
    AstrometryMapping *findMapping(CcdImage const &ccdImage) const override;
};
}  // namespace jointcal
}  // namespace lsst

#endif  // LSST_JOINTCAL_SIMPLE_ASTROMETRY_MODEL_H
