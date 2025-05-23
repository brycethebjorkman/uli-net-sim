//
// Generated file, do not edit! Created by opp_msgtool 6.1 from rid_beacon/RidBeaconFrame.msg.
//

// Disable warnings about unused variables, empty switch stmts, etc:
#ifdef _MSC_VER
#  pragma warning(disable:4101)
#  pragma warning(disable:4065)
#endif

#if defined(__clang__)
#  pragma clang diagnostic ignored "-Wshadow"
#  pragma clang diagnostic ignored "-Wconversion"
#  pragma clang diagnostic ignored "-Wunused-parameter"
#  pragma clang diagnostic ignored "-Wc++98-compat"
#  pragma clang diagnostic ignored "-Wunreachable-code-break"
#  pragma clang diagnostic ignored "-Wold-style-cast"
#elif defined(__GNUC__)
#  pragma GCC diagnostic ignored "-Wshadow"
#  pragma GCC diagnostic ignored "-Wconversion"
#  pragma GCC diagnostic ignored "-Wunused-parameter"
#  pragma GCC diagnostic ignored "-Wold-style-cast"
#  pragma GCC diagnostic ignored "-Wsuggest-attribute=noreturn"
#  pragma GCC diagnostic ignored "-Wfloat-conversion"
#endif

#include <iostream>
#include <sstream>
#include <memory>
#include <type_traits>
#include "RidBeaconFrame_m.h"

namespace omnetpp {

// Template pack/unpack rules. They are declared *after* a1l type-specific pack functions for multiple reasons.
// They are in the omnetpp namespace, to allow them to be found by argument-dependent lookup via the cCommBuffer argument

// Packing/unpacking an std::vector
template<typename T, typename A>
void doParsimPacking(omnetpp::cCommBuffer *buffer, const std::vector<T,A>& v)
{
    int n = v.size();
    doParsimPacking(buffer, n);
    for (int i = 0; i < n; i++)
        doParsimPacking(buffer, v[i]);
}

template<typename T, typename A>
void doParsimUnpacking(omnetpp::cCommBuffer *buffer, std::vector<T,A>& v)
{
    int n;
    doParsimUnpacking(buffer, n);
    v.resize(n);
    for (int i = 0; i < n; i++)
        doParsimUnpacking(buffer, v[i]);
}

// Packing/unpacking an std::list
template<typename T, typename A>
void doParsimPacking(omnetpp::cCommBuffer *buffer, const std::list<T,A>& l)
{
    doParsimPacking(buffer, (int)l.size());
    for (typename std::list<T,A>::const_iterator it = l.begin(); it != l.end(); ++it)
        doParsimPacking(buffer, (T&)*it);
}

template<typename T, typename A>
void doParsimUnpacking(omnetpp::cCommBuffer *buffer, std::list<T,A>& l)
{
    int n;
    doParsimUnpacking(buffer, n);
    for (int i = 0; i < n; i++) {
        l.push_back(T());
        doParsimUnpacking(buffer, l.back());
    }
}

// Packing/unpacking an std::set
template<typename T, typename Tr, typename A>
void doParsimPacking(omnetpp::cCommBuffer *buffer, const std::set<T,Tr,A>& s)
{
    doParsimPacking(buffer, (int)s.size());
    for (typename std::set<T,Tr,A>::const_iterator it = s.begin(); it != s.end(); ++it)
        doParsimPacking(buffer, *it);
}

template<typename T, typename Tr, typename A>
void doParsimUnpacking(omnetpp::cCommBuffer *buffer, std::set<T,Tr,A>& s)
{
    int n;
    doParsimUnpacking(buffer, n);
    for (int i = 0; i < n; i++) {
        T x;
        doParsimUnpacking(buffer, x);
        s.insert(x);
    }
}

// Packing/unpacking an std::map
template<typename K, typename V, typename Tr, typename A>
void doParsimPacking(omnetpp::cCommBuffer *buffer, const std::map<K,V,Tr,A>& m)
{
    doParsimPacking(buffer, (int)m.size());
    for (typename std::map<K,V,Tr,A>::const_iterator it = m.begin(); it != m.end(); ++it) {
        doParsimPacking(buffer, it->first);
        doParsimPacking(buffer, it->second);
    }
}

template<typename K, typename V, typename Tr, typename A>
void doParsimUnpacking(omnetpp::cCommBuffer *buffer, std::map<K,V,Tr,A>& m)
{
    int n;
    doParsimUnpacking(buffer, n);
    for (int i = 0; i < n; i++) {
        K k; V v;
        doParsimUnpacking(buffer, k);
        doParsimUnpacking(buffer, v);
        m[k] = v;
    }
}

// Default pack/unpack function for arrays
template<typename T>
void doParsimArrayPacking(omnetpp::cCommBuffer *b, const T *t, int n)
{
    for (int i = 0; i < n; i++)
        doParsimPacking(b, t[i]);
}

template<typename T>
void doParsimArrayUnpacking(omnetpp::cCommBuffer *b, T *t, int n)
{
    for (int i = 0; i < n; i++)
        doParsimUnpacking(b, t[i]);
}

// Default rule to prevent compiler from choosing base class' doParsimPacking() function
template<typename T>
void doParsimPacking(omnetpp::cCommBuffer *, const T& t)
{
    throw omnetpp::cRuntimeError("Parsim error: No doParsimPacking() function for type %s", omnetpp::opp_typename(typeid(t)));
}

template<typename T>
void doParsimUnpacking(omnetpp::cCommBuffer *, T& t)
{
    throw omnetpp::cRuntimeError("Parsim error: No doParsimUnpacking() function for type %s", omnetpp::opp_typename(typeid(t)));
}

}  // namespace omnetpp

namespace inet {
namespace ieee80211 {

Register_Class(RidBeaconFrame)

RidBeaconFrame::RidBeaconFrame() : ::inet::ieee80211::Ieee80211BeaconFrame()
{
}

RidBeaconFrame::RidBeaconFrame(const RidBeaconFrame& other) : ::inet::ieee80211::Ieee80211BeaconFrame(other)
{
    copy(other);
}

RidBeaconFrame::~RidBeaconFrame()
{
}

RidBeaconFrame& RidBeaconFrame::operator=(const RidBeaconFrame& other)
{
    if (this == &other) return *this;
    ::inet::ieee80211::Ieee80211BeaconFrame::operator=(other);
    copy(other);
    return *this;
}

void RidBeaconFrame::copy(const RidBeaconFrame& other)
{
    this->serialNumber = other.serialNumber;
    this->timestamp = other.timestamp;
    this->emergencyStatus = other.emergencyStatus;
    this->posX = other.posX;
    this->posY = other.posY;
    this->posZ = other.posZ;
}

void RidBeaconFrame::parsimPack(omnetpp::cCommBuffer *b) const
{
    ::inet::ieee80211::Ieee80211BeaconFrame::parsimPack(b);
    doParsimPacking(b,this->serialNumber);
    doParsimPacking(b,this->timestamp);
    doParsimPacking(b,this->emergencyStatus);
    doParsimPacking(b,this->posX);
    doParsimPacking(b,this->posY);
    doParsimPacking(b,this->posZ);
}

void RidBeaconFrame::parsimUnpack(omnetpp::cCommBuffer *b)
{
    ::inet::ieee80211::Ieee80211BeaconFrame::parsimUnpack(b);
    doParsimUnpacking(b,this->serialNumber);
    doParsimUnpacking(b,this->timestamp);
    doParsimUnpacking(b,this->emergencyStatus);
    doParsimUnpacking(b,this->posX);
    doParsimUnpacking(b,this->posY);
    doParsimUnpacking(b,this->posZ);
}

int RidBeaconFrame::getSerialNumber() const
{
    return this->serialNumber;
}

void RidBeaconFrame::setSerialNumber(int serialNumber)
{
    handleChange();
    this->serialNumber = serialNumber;
}

int64_t RidBeaconFrame::getTimestamp() const
{
    return this->timestamp;
}

void RidBeaconFrame::setTimestamp(int64_t timestamp)
{
    handleChange();
    this->timestamp = timestamp;
}

bool RidBeaconFrame::getEmergencyStatus() const
{
    return this->emergencyStatus;
}

void RidBeaconFrame::setEmergencyStatus(bool emergencyStatus)
{
    handleChange();
    this->emergencyStatus = emergencyStatus;
}

double RidBeaconFrame::getPosX() const
{
    return this->posX;
}

void RidBeaconFrame::setPosX(double posX)
{
    handleChange();
    this->posX = posX;
}

double RidBeaconFrame::getPosY() const
{
    return this->posY;
}

void RidBeaconFrame::setPosY(double posY)
{
    handleChange();
    this->posY = posY;
}

double RidBeaconFrame::getPosZ() const
{
    return this->posZ;
}

void RidBeaconFrame::setPosZ(double posZ)
{
    handleChange();
    this->posZ = posZ;
}

class RidBeaconFrameDescriptor : public omnetpp::cClassDescriptor
{
  private:
    mutable const char **propertyNames;
    enum FieldConstants {
        FIELD_serialNumber,
        FIELD_timestamp,
        FIELD_emergencyStatus,
        FIELD_posX,
        FIELD_posY,
        FIELD_posZ,
    };
  public:
    RidBeaconFrameDescriptor();
    virtual ~RidBeaconFrameDescriptor();

    virtual bool doesSupport(omnetpp::cObject *obj) const override;
    virtual const char **getPropertyNames() const override;
    virtual const char *getProperty(const char *propertyName) const override;
    virtual int getFieldCount() const override;
    virtual const char *getFieldName(int field) const override;
    virtual int findField(const char *fieldName) const override;
    virtual unsigned int getFieldTypeFlags(int field) const override;
    virtual const char *getFieldTypeString(int field) const override;
    virtual const char **getFieldPropertyNames(int field) const override;
    virtual const char *getFieldProperty(int field, const char *propertyName) const override;
    virtual int getFieldArraySize(omnetpp::any_ptr object, int field) const override;
    virtual void setFieldArraySize(omnetpp::any_ptr object, int field, int size) const override;

    virtual const char *getFieldDynamicTypeString(omnetpp::any_ptr object, int field, int i) const override;
    virtual std::string getFieldValueAsString(omnetpp::any_ptr object, int field, int i) const override;
    virtual void setFieldValueAsString(omnetpp::any_ptr object, int field, int i, const char *value) const override;
    virtual omnetpp::cValue getFieldValue(omnetpp::any_ptr object, int field, int i) const override;
    virtual void setFieldValue(omnetpp::any_ptr object, int field, int i, const omnetpp::cValue& value) const override;

    virtual const char *getFieldStructName(int field) const override;
    virtual omnetpp::any_ptr getFieldStructValuePointer(omnetpp::any_ptr object, int field, int i) const override;
    virtual void setFieldStructValuePointer(omnetpp::any_ptr object, int field, int i, omnetpp::any_ptr ptr) const override;
};

Register_ClassDescriptor(RidBeaconFrameDescriptor)

RidBeaconFrameDescriptor::RidBeaconFrameDescriptor() : omnetpp::cClassDescriptor(omnetpp::opp_typename(typeid(inet::ieee80211::RidBeaconFrame)), "inet::ieee80211::Ieee80211BeaconFrame")
{
    propertyNames = nullptr;
}

RidBeaconFrameDescriptor::~RidBeaconFrameDescriptor()
{
    delete[] propertyNames;
}

bool RidBeaconFrameDescriptor::doesSupport(omnetpp::cObject *obj) const
{
    return dynamic_cast<RidBeaconFrame *>(obj)!=nullptr;
}

const char **RidBeaconFrameDescriptor::getPropertyNames() const
{
    if (!propertyNames) {
        static const char *names[] = {  nullptr };
        omnetpp::cClassDescriptor *base = getBaseClassDescriptor();
        const char **baseNames = base ? base->getPropertyNames() : nullptr;
        propertyNames = mergeLists(baseNames, names);
    }
    return propertyNames;
}

const char *RidBeaconFrameDescriptor::getProperty(const char *propertyName) const
{
    omnetpp::cClassDescriptor *base = getBaseClassDescriptor();
    return base ? base->getProperty(propertyName) : nullptr;
}

int RidBeaconFrameDescriptor::getFieldCount() const
{
    omnetpp::cClassDescriptor *base = getBaseClassDescriptor();
    return base ? 6+base->getFieldCount() : 6;
}

unsigned int RidBeaconFrameDescriptor::getFieldTypeFlags(int field) const
{
    omnetpp::cClassDescriptor *base = getBaseClassDescriptor();
    if (base) {
        if (field < base->getFieldCount())
            return base->getFieldTypeFlags(field);
        field -= base->getFieldCount();
    }
    static unsigned int fieldTypeFlags[] = {
        FD_ISEDITABLE,    // FIELD_serialNumber
        FD_ISEDITABLE,    // FIELD_timestamp
        FD_ISEDITABLE,    // FIELD_emergencyStatus
        FD_ISEDITABLE,    // FIELD_posX
        FD_ISEDITABLE,    // FIELD_posY
        FD_ISEDITABLE,    // FIELD_posZ
    };
    return (field >= 0 && field < 6) ? fieldTypeFlags[field] : 0;
}

const char *RidBeaconFrameDescriptor::getFieldName(int field) const
{
    omnetpp::cClassDescriptor *base = getBaseClassDescriptor();
    if (base) {
        if (field < base->getFieldCount())
            return base->getFieldName(field);
        field -= base->getFieldCount();
    }
    static const char *fieldNames[] = {
        "serialNumber",
        "timestamp",
        "emergencyStatus",
        "posX",
        "posY",
        "posZ",
    };
    return (field >= 0 && field < 6) ? fieldNames[field] : nullptr;
}

int RidBeaconFrameDescriptor::findField(const char *fieldName) const
{
    omnetpp::cClassDescriptor *base = getBaseClassDescriptor();
    int baseIndex = base ? base->getFieldCount() : 0;
    if (strcmp(fieldName, "serialNumber") == 0) return baseIndex + 0;
    if (strcmp(fieldName, "timestamp") == 0) return baseIndex + 1;
    if (strcmp(fieldName, "emergencyStatus") == 0) return baseIndex + 2;
    if (strcmp(fieldName, "posX") == 0) return baseIndex + 3;
    if (strcmp(fieldName, "posY") == 0) return baseIndex + 4;
    if (strcmp(fieldName, "posZ") == 0) return baseIndex + 5;
    return base ? base->findField(fieldName) : -1;
}

const char *RidBeaconFrameDescriptor::getFieldTypeString(int field) const
{
    omnetpp::cClassDescriptor *base = getBaseClassDescriptor();
    if (base) {
        if (field < base->getFieldCount())
            return base->getFieldTypeString(field);
        field -= base->getFieldCount();
    }
    static const char *fieldTypeStrings[] = {
        "int",    // FIELD_serialNumber
        "int64_t",    // FIELD_timestamp
        "bool",    // FIELD_emergencyStatus
        "double",    // FIELD_posX
        "double",    // FIELD_posY
        "double",    // FIELD_posZ
    };
    return (field >= 0 && field < 6) ? fieldTypeStrings[field] : nullptr;
}

const char **RidBeaconFrameDescriptor::getFieldPropertyNames(int field) const
{
    omnetpp::cClassDescriptor *base = getBaseClassDescriptor();
    if (base) {
        if (field < base->getFieldCount())
            return base->getFieldPropertyNames(field);
        field -= base->getFieldCount();
    }
    switch (field) {
        default: return nullptr;
    }
}

const char *RidBeaconFrameDescriptor::getFieldProperty(int field, const char *propertyName) const
{
    omnetpp::cClassDescriptor *base = getBaseClassDescriptor();
    if (base) {
        if (field < base->getFieldCount())
            return base->getFieldProperty(field, propertyName);
        field -= base->getFieldCount();
    }
    switch (field) {
        default: return nullptr;
    }
}

int RidBeaconFrameDescriptor::getFieldArraySize(omnetpp::any_ptr object, int field) const
{
    omnetpp::cClassDescriptor *base = getBaseClassDescriptor();
    if (base) {
        if (field < base->getFieldCount())
            return base->getFieldArraySize(object, field);
        field -= base->getFieldCount();
    }
    RidBeaconFrame *pp = omnetpp::fromAnyPtr<RidBeaconFrame>(object); (void)pp;
    switch (field) {
        default: return 0;
    }
}

void RidBeaconFrameDescriptor::setFieldArraySize(omnetpp::any_ptr object, int field, int size) const
{
    omnetpp::cClassDescriptor *base = getBaseClassDescriptor();
    if (base) {
        if (field < base->getFieldCount()){
            base->setFieldArraySize(object, field, size);
            return;
        }
        field -= base->getFieldCount();
    }
    RidBeaconFrame *pp = omnetpp::fromAnyPtr<RidBeaconFrame>(object); (void)pp;
    switch (field) {
        default: throw omnetpp::cRuntimeError("Cannot set array size of field %d of class 'RidBeaconFrame'", field);
    }
}

const char *RidBeaconFrameDescriptor::getFieldDynamicTypeString(omnetpp::any_ptr object, int field, int i) const
{
    omnetpp::cClassDescriptor *base = getBaseClassDescriptor();
    if (base) {
        if (field < base->getFieldCount())
            return base->getFieldDynamicTypeString(object,field,i);
        field -= base->getFieldCount();
    }
    RidBeaconFrame *pp = omnetpp::fromAnyPtr<RidBeaconFrame>(object); (void)pp;
    switch (field) {
        default: return nullptr;
    }
}

std::string RidBeaconFrameDescriptor::getFieldValueAsString(omnetpp::any_ptr object, int field, int i) const
{
    omnetpp::cClassDescriptor *base = getBaseClassDescriptor();
    if (base) {
        if (field < base->getFieldCount())
            return base->getFieldValueAsString(object,field,i);
        field -= base->getFieldCount();
    }
    RidBeaconFrame *pp = omnetpp::fromAnyPtr<RidBeaconFrame>(object); (void)pp;
    switch (field) {
        case FIELD_serialNumber: return long2string(pp->getSerialNumber());
        case FIELD_timestamp: return int642string(pp->getTimestamp());
        case FIELD_emergencyStatus: return bool2string(pp->getEmergencyStatus());
        case FIELD_posX: return double2string(pp->getPosX());
        case FIELD_posY: return double2string(pp->getPosY());
        case FIELD_posZ: return double2string(pp->getPosZ());
        default: return "";
    }
}

void RidBeaconFrameDescriptor::setFieldValueAsString(omnetpp::any_ptr object, int field, int i, const char *value) const
{
    omnetpp::cClassDescriptor *base = getBaseClassDescriptor();
    if (base) {
        if (field < base->getFieldCount()){
            base->setFieldValueAsString(object, field, i, value);
            return;
        }
        field -= base->getFieldCount();
    }
    RidBeaconFrame *pp = omnetpp::fromAnyPtr<RidBeaconFrame>(object); (void)pp;
    switch (field) {
        case FIELD_serialNumber: pp->setSerialNumber(string2long(value)); break;
        case FIELD_timestamp: pp->setTimestamp(string2int64(value)); break;
        case FIELD_emergencyStatus: pp->setEmergencyStatus(string2bool(value)); break;
        case FIELD_posX: pp->setPosX(string2double(value)); break;
        case FIELD_posY: pp->setPosY(string2double(value)); break;
        case FIELD_posZ: pp->setPosZ(string2double(value)); break;
        default: throw omnetpp::cRuntimeError("Cannot set field %d of class 'RidBeaconFrame'", field);
    }
}

omnetpp::cValue RidBeaconFrameDescriptor::getFieldValue(omnetpp::any_ptr object, int field, int i) const
{
    omnetpp::cClassDescriptor *base = getBaseClassDescriptor();
    if (base) {
        if (field < base->getFieldCount())
            return base->getFieldValue(object,field,i);
        field -= base->getFieldCount();
    }
    RidBeaconFrame *pp = omnetpp::fromAnyPtr<RidBeaconFrame>(object); (void)pp;
    switch (field) {
        case FIELD_serialNumber: return pp->getSerialNumber();
        case FIELD_timestamp: return pp->getTimestamp();
        case FIELD_emergencyStatus: return pp->getEmergencyStatus();
        case FIELD_posX: return pp->getPosX();
        case FIELD_posY: return pp->getPosY();
        case FIELD_posZ: return pp->getPosZ();
        default: throw omnetpp::cRuntimeError("Cannot return field %d of class 'RidBeaconFrame' as cValue -- field index out of range?", field);
    }
}

void RidBeaconFrameDescriptor::setFieldValue(omnetpp::any_ptr object, int field, int i, const omnetpp::cValue& value) const
{
    omnetpp::cClassDescriptor *base = getBaseClassDescriptor();
    if (base) {
        if (field < base->getFieldCount()){
            base->setFieldValue(object, field, i, value);
            return;
        }
        field -= base->getFieldCount();
    }
    RidBeaconFrame *pp = omnetpp::fromAnyPtr<RidBeaconFrame>(object); (void)pp;
    switch (field) {
        case FIELD_serialNumber: pp->setSerialNumber(omnetpp::checked_int_cast<int>(value.intValue())); break;
        case FIELD_timestamp: pp->setTimestamp(omnetpp::checked_int_cast<int64_t>(value.intValue())); break;
        case FIELD_emergencyStatus: pp->setEmergencyStatus(value.boolValue()); break;
        case FIELD_posX: pp->setPosX(value.doubleValue()); break;
        case FIELD_posY: pp->setPosY(value.doubleValue()); break;
        case FIELD_posZ: pp->setPosZ(value.doubleValue()); break;
        default: throw omnetpp::cRuntimeError("Cannot set field %d of class 'RidBeaconFrame'", field);
    }
}

const char *RidBeaconFrameDescriptor::getFieldStructName(int field) const
{
    omnetpp::cClassDescriptor *base = getBaseClassDescriptor();
    if (base) {
        if (field < base->getFieldCount())
            return base->getFieldStructName(field);
        field -= base->getFieldCount();
    }
    switch (field) {
        default: return nullptr;
    };
}

omnetpp::any_ptr RidBeaconFrameDescriptor::getFieldStructValuePointer(omnetpp::any_ptr object, int field, int i) const
{
    omnetpp::cClassDescriptor *base = getBaseClassDescriptor();
    if (base) {
        if (field < base->getFieldCount())
            return base->getFieldStructValuePointer(object, field, i);
        field -= base->getFieldCount();
    }
    RidBeaconFrame *pp = omnetpp::fromAnyPtr<RidBeaconFrame>(object); (void)pp;
    switch (field) {
        default: return omnetpp::any_ptr(nullptr);
    }
}

void RidBeaconFrameDescriptor::setFieldStructValuePointer(omnetpp::any_ptr object, int field, int i, omnetpp::any_ptr ptr) const
{
    omnetpp::cClassDescriptor *base = getBaseClassDescriptor();
    if (base) {
        if (field < base->getFieldCount()){
            base->setFieldStructValuePointer(object, field, i, ptr);
            return;
        }
        field -= base->getFieldCount();
    }
    RidBeaconFrame *pp = omnetpp::fromAnyPtr<RidBeaconFrame>(object); (void)pp;
    switch (field) {
        default: throw omnetpp::cRuntimeError("Cannot set field %d of class 'RidBeaconFrame'", field);
    }
}

}  // namespace ieee80211
}  // namespace inet

namespace omnetpp {

}  // namespace omnetpp

